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
        response = requests.get(requestUrl, params=requestParams)
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


def pullMediaWithinLastNDays(accessToken, userId, days):
    """
    Paginate through posts (newest first) and collect every post from the
    last N days - not just the first page. Stops as soon as a post older
    than the window is reached, since Instagram returns posts in reverse
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
        response = requests.get(requestUrl, params=requestParams)
        response.raise_for_status()
        responseData = response.json()
        pageCount += 1

        reachedOlderPost = False
        for mediaItem in responseData.get("data", []):
            if isWithinLastNDays(mediaItem.get("timestamp", ""), days):
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

    print(f"  (scanned {pageCount} page(s) of posts to find everything in the last {days} day(s))")
    return collectedItems


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
    )

    if not response.ok:
        return None, response.json().get("error", {}).get("message", response.text)

    dailyValues = response.json().get("data", [{}])[0].get("values", [])
    totalReach = sum(entry.get("value", 0) for entry in dailyValues)

    return totalReach, None


def isWithinLastNDays(isoTimestamp, days):
    """Check whether a post's timestamp falls within the last N days."""
    try:
        postDate = datetime.fromisoformat(isoTimestamp)
    except (ValueError, TypeError):
        return False

    cutoffDate = datetime.now(timezone.utc) - timedelta(days=days)
    return postDate >= cutoffDate


def calculateEngagementRate(mediaItem, followersCount):
    """Calculate (likes + comments) / followers as a percentage."""
    if not followersCount:
        return 0

    likeCount = mediaItem.get("like_count", 0)
    commentsCount = mediaItem.get("comments_count", 0)
    return (likeCount + commentsCount) / followersCount * 100
