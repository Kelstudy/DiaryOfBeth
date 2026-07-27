"""
igApi.py

Shared Instagram Graph API pull logic, used by pullData.py (the automated
collector). Kept separate from any print/CLI code so it can be imported
cleanly.
"""

import json
import time
from datetime import datetime, timedelta, timezone

import requests


BASE_URL = "https://graph.instagram.com"

# Every request below passes this. Without an explicit timeout, requests
# waits forever on a stalled connection - with a pulled-post count now in
# the hundreds (each needing its own insights call), a single stalled
# request with no timeout hangs the entire GitHub Actions job until it
# hits the runner's multi-hour default limit, which is what actually
# happened on 2026-07-27.
REQUEST_TIMEOUT_SECONDS = 30

# Default post count when pulling by post count rather than by day window.
DEFAULT_POST_COUNT = 10

# Page size used while paginating through posts to build the N-day overview.
# This does NOT cap how many posts get counted - pagination continues across
# as many pages as needed until a post older than the requested window is reached.
SCAN_PAGE_SIZE = 25


def loadToken(tokenPath="token.json"):
    """Load the access token saved by getAccessToken.py."""
    try:
        with open(tokenPath, "r") as tokenFile:
            tokenRecord = json.load(tokenFile)
    except FileNotFoundError:
        raise RuntimeError(
            f"{tokenPath} not found. Run getAccessToken.py first to generate a token."
        )

    return tokenRecord["accessToken"], tokenRecord["userId"]


def pullProfile(accessToken, userId):
    """Pull basic profile fields."""
    profileFields = "id,username,account_type,followers_count,follows_count,media_count"

    response = requests.get(
        f"{BASE_URL}/{userId}",
        params={"fields": profileFields, "access_token": accessToken},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def pullMostRecentPosts(accessToken, userId, postCount):
    """
    Paginate through posts (newest first) and collect exactly postCount of
    them (or fewer, if the account has posted less than that). Paginates
    rather than issuing a single request with limit=postCount, since a
    large postCount can exceed what the API returns in one page.
    """
    mediaFields = (
        "id,caption,media_type,media_product_type,"
        "timestamp,permalink,like_count,comments_count"
    )

    requestUrl = f"{BASE_URL}/{userId}/media"
    requestParams = {
        "fields": mediaFields,
        "limit": min(SCAN_PAGE_SIZE, postCount),
        "access_token": accessToken,
    }

    collectedItems = []

    while requestUrl and len(collectedItems) < postCount:
        response = requests.get(requestUrl, params=requestParams, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        responseData = response.json()

        collectedItems.extend(responseData.get("data", []))

        nextPageUrl = responseData.get("paging", {}).get("next")
        if not nextPageUrl:
            break

        # The "next" URL already includes all needed query params (including
        # the access token), so switch to using it directly with no extra params.
        requestUrl = nextPageUrl
        requestParams = None

    return collectedItems[:postCount]


def pullMediaSinceDate(accessToken, userId, cutoffDate):
    """
    Paginate through posts (newest first) and collect every post at or after
    cutoffDate - not just the first page. Stops as soon as a post older than
    cutoffDate is reached, since Instagram returns posts in reverse
    chronological order, so nothing beyond that point can still be in range.

    This means the number of posts returned is exact, not limited by a
    fixed page size like a plain single-page pull would be.
    """
    mediaFields = (
        "id,caption,media_type,media_product_type,"
        "timestamp,permalink,like_count,comments_count"
    )

    requestUrl = f"{BASE_URL}/{userId}/media"
    requestParams = {
        "fields": mediaFields,
        "limit": SCAN_PAGE_SIZE,
        "access_token": accessToken,
    }

    collectedItems = []
    pageCount = 0

    while requestUrl:
        response = requests.get(requestUrl, params=requestParams, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        responseData = response.json()
        pageCount += 1

        reachedOlderPost = False
        for mediaItem in responseData.get("data", []):
            if isAtOrAfter(mediaItem.get("timestamp", ""), cutoffDate):
                collectedItems.append(mediaItem)
            else:
                reachedOlderPost = True
                break

        if reachedOlderPost:
            break

        nextPageUrl = responseData.get("paging", {}).get("next")
        if not nextPageUrl:
            break

        # The "next" URL already includes all needed query params (including
        # the access token), so switch to using it directly with no extra params.
        requestUrl = nextPageUrl
        requestParams = None

    print(f"  (scanned {pageCount} page(s) of posts to find everything since {cutoffDate.date()})")
    return collectedItems


def pullMediaWithinLastNDays(accessToken, userId, days):
    """Collect every post from the last N days (see pullMediaSinceDate)."""
    cutoffDate = datetime.now(timezone.utc) - timedelta(days=days)
    return pullMediaSinceDate(accessToken, userId, cutoffDate)


def getMetricListForProductType(productType):
    """
    Return the correct insight metric list for a given media product type.

    Confirmed via live testing against this account:
      - REELS supports "views" but NOT "impressions"
      - Photos/carousels are expected to support "impressions" instead of "views"
        (auto-falls-back below if that assumption turns out to be wrong)
    """
    commonMetrics = ["reach", "saved", "shares", "total_interactions"]

    if productType == "REELS":
        return commonMetrics + ["views"]
    else:
        return commonMetrics + ["impressions"]


def pullMediaInsights(accessToken, mediaId, productType):
    """
    Pull insights for one post, using the metric list for its product type.

    Tries all metrics in a single request first (cheaper on the rate limit).
    If that fails, falls back to requesting metrics one at a time and simply
    drops whichever ones error out, so a single unsupported metric doesn't
    block the rest of the data for that post.
    """
    metricList = getMetricListForProductType(productType)

    combinedResponse = requests.get(
        f"{BASE_URL}/{mediaId}/insights",
        params={"metric": ",".join(metricList), "access_token": accessToken},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if combinedResponse.ok:
        insightValues = {}
        for metricEntry in combinedResponse.json().get("data", []):
            insightValues[metricEntry["name"]] = metricEntry["values"][0]["value"]
        return insightValues

    # Combined call failed (likely one bad metric for this post) - fall back
    # to testing metrics individually and keep only the ones that work.
    insightValues = {}
    for metricName in metricList:
        singleResponse = requests.get(
            f"{BASE_URL}/{mediaId}/insights",
            params={"metric": metricName, "access_token": accessToken},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if singleResponse.ok:
            metricEntry = singleResponse.json()["data"][0]
            insightValues[metricName] = metricEntry["values"][0]["value"]

    return insightValues


def pullAccountReachLastNDays(accessToken, userId, days):
    """
    Pull account-level daily reach for the last N days and sum it.

    Note: summing daily "unique reach" values is an approximation - the same
    person reached on multiple days gets counted more than once. It's still
    a useful trend indicator for a media kit, just not a literal unique-account
    count. Flagging this rather than presenting it as more precise than it is.
    """
    untilTime = int(time.time())
    sinceTime = untilTime - (days * 24 * 60 * 60)

    response = requests.get(
        f"{BASE_URL}/{userId}/insights",
        params={
            "metric": "reach",
            "period": "day",
            "since": sinceTime,
            "until": untilTime,
            "access_token": accessToken,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    dailyValues = response.json().get("data", [{}])[0].get("values", [])
    totalReach = sum(entry.get("value", 0) for entry in dailyValues)

    return totalReach, None


def pullAccountProfileViewsLastNDays(accessToken, userId, days):
    """
    Pull the total number of profile visits over the last N days.

    Unlike reach, profile_views is a "total value" metric on this API - it
    does not support a period=day time series and instead requires
    metric_type=total_value, returning one already-summed number rather
    than a list of daily values to add up (confirmed via live testing
    against this account; a plain period=day request returns an empty
    data array with no error).
    """
    untilTime = int(time.time())
    sinceTime = untilTime - (days * 24 * 60 * 60)

    response = requests.get(
        f"{BASE_URL}/{userId}/insights",
        params={
            "metric": "profile_views",
            "period": "day",
            "metric_type": "total_value",
            "since": sinceTime,
            "until": untilTime,
            "access_token": accessToken,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    responseData = response.json().get("data", [{}])
    if not responseData:
        return None, "No profile_views data returned"

    totalProfileViews = responseData[0].get("total_value", {}).get("value", 0)

    return totalProfileViews, None


def pullAccountViewsLastNDays(accessToken, userId, days):
    """
    Pull total content views (reels, posts, and stories combined - "the
    number of times your content was played or displayed") over the last
    N days. Not the same metric as profile_views - a much bigger number,
    since it counts every content play, not just profile-page visits. This
    is what the Instagram app's own "Views" figure in account insights
    refers to. Same total-value shape as profile_views.
    """
    untilTime = int(time.time())
    sinceTime = untilTime - (days * 24 * 60 * 60)

    response = requests.get(
        f"{BASE_URL}/{userId}/insights",
        params={
            "metric": "views",
            "period": "day",
            "metric_type": "total_value",
            "since": sinceTime,
            "until": untilTime,
            "access_token": accessToken,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    responseData = response.json().get("data", [{}])
    if not responseData:
        return None, "No views data returned"

    totalViews = responseData[0].get("total_value", {}).get("value", 0)

    return totalViews, None


def pullNetFollowersLastNDays(accessToken, userId, days):
    """
    Pull net follower change over the last N days - new follows minus
    unfollows/account deletions - matching the "Net followers" figure
    Instagram's own app shows on the Insights overview screen. Uses
    follows_and_unfollows with a follow_type breakdown: FOLLOWER is new
    follows in the window, NON_FOLLOWER is unfollows/deletions; confirmed
    live that FOLLOWER - NON_FOLLOWER lines up closely with the app's own
    reported net figure for the same window (small gaps expected purely
    from pull-timing, not a discrepancy in the math).

    This is a real window total from the API, unlike comparing the
    point-in-time follower count between two pulls (which is close to
    meaningless when pulls are only hours apart rather than a full
    window).
    """
    untilTime = int(time.time())
    sinceTime = untilTime - (days * 24 * 60 * 60)

    response = requests.get(
        f"{BASE_URL}/{userId}/insights",
        params={
            "metric": "follows_and_unfollows",
            "period": "day",
            "metric_type": "total_value",
            "breakdown": "follow_type",
            "since": sinceTime,
            "until": untilTime,
            "access_token": accessToken,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    responseData = response.json().get("data", [{}])
    if not responseData:
        return None, "No follows_and_unfollows data returned"

    breakdowns = responseData[0].get("total_value", {}).get("breakdowns", [{}])
    results = breakdowns[0].get("results", []) if breakdowns else []

    newFollows = 0
    unfollows = 0
    for entry in results:
        if entry.get("dimension_values") == ["FOLLOWER"]:
            newFollows = entry.get("value", 0)
        elif entry.get("dimension_values") == ["NON_FOLLOWER"]:
            unfollows = entry.get("value", 0)

    return newFollows - unfollows, None


def pullFollowerDemographics(accessToken, userId, breakdown):
    """
    Pull a follower demographic breakdown - confirmed live to accept
    breakdown="age,gender" (combined), "country", or "city". Lifetime/
    current-snapshot data, not a day-window metric like reach or profile
    views, so it's pulled once per run rather than over a since/until range.

    Returns a list of {"dimensionValues": [...], "value": N} dicts (the
    raw dimension_values order matches the requested breakdown fields, e.g.
    ["25-34", "F"] for breakdown="age,gender"), or (None, error).
    """
    response = requests.get(
        f"{BASE_URL}/{userId}/insights",
        params={
            "metric": "follower_demographics",
            "period": "lifetime",
            "metric_type": "total_value",
            "breakdown": breakdown,
            "access_token": accessToken,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    responseData = response.json().get("data", [{}])
    if not responseData:
        return None, "No follower_demographics data returned"

    breakdowns = responseData[0].get("total_value", {}).get("breakdowns", [{}])
    rawResults = breakdowns[0].get("results", []) if breakdowns else []

    results = [
        {"dimensionValues": entry.get("dimension_values", []), "value": entry.get("value", 0)}
        for entry in rawResults
    ]

    return results, None


def isAtOrAfter(isoTimestamp, cutoffDate):
    """Check whether a post's timestamp falls at or after cutoffDate."""
    try:
        postDate = datetime.fromisoformat(isoTimestamp)
    except (ValueError, TypeError):
        return False

    return postDate >= cutoffDate


def calculateEngagementRate(mediaItem, followersCount):
    """Calculate (likes + comments) / followers as a percentage."""
    if not followersCount:
        return 0

    likeCount = mediaItem.get("like_count", 0)
    commentsCount = mediaItem.get("comments_count", 0)
    return (likeCount + commentsCount) / followersCount * 100
