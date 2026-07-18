"""
testPull.py

Sanity-check script with three sections:
  1. Detailed stats for your last 10 posts (engagement, insights)
  2. A summary of those same 10 posts
  3. A separate overview of everything posted in the last 30 days

This is a readable, human-facing summary - not the final automated data
collector. Once this looks right, the same logic gets reused inside
pullData.py to append a JSON record instead of printing to the terminal.

Run with:
  python testPull.py
"""

import json
import textwrap
import time
from datetime import datetime, timedelta, timezone

import requests


BASE_URL = "https://graph.instagram.com"

# How many of your most recent posts to show in full detail.
DETAILED_POST_COUNT = 10

# Page size used while paginating through posts to build the 30-day overview.
# This does NOT cap how many posts get counted - pagination continues across
# as many pages as needed until a post older than 30 days is reached.
MONTHLY_SCAN_PAGE_SIZE = 25


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


def pullRecentMedia(accessToken, userId, mediaLimit):
    """Pull the most recent posts with basic engagement fields."""
    mediaFields = (
        "id,caption,media_type,media_product_type,"
        "timestamp,permalink,like_count,comments_count"
    )

    response = requests.get(
        f"{BASE_URL}/{userId}/media",
        params={"fields": mediaFields, "limit": mediaLimit, "access_token": accessToken},
    )
    response.raise_for_status()
    return response.json().get("data", [])


def pullMediaWithinLast30Days(accessToken, userId):
    """
    Paginate through posts (newest first) and collect every post from the
    last 30 days - not just the first page. Stops as soon as a post older
    than 30 days is reached, since Instagram returns posts in reverse
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
        "limit": MONTHLY_SCAN_PAGE_SIZE,
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
            if isWithinLast30Days(mediaItem.get("timestamp", "")):
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

    print(f"  (scanned {pageCount} page(s) of posts to find everything in the last 30 days)")
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


def pullAccountReachLast30Days(accessToken, userId):
    """
    Pull account-level daily reach for the last 30 days and sum it.

    Note: summing daily "unique reach" values is an approximation - the same
    person reached on multiple days gets counted more than once. It's still
    a useful trend indicator for a media kit, just not a literal unique-account
    count. Flagging this rather than presenting it as more precise than it is.
    """
    untilTime = int(time.time())
    sinceTime = untilTime - (30 * 24 * 60 * 60)

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


def formatTimestamp(isoTimestamp):
    """Turn Instagram's ISO timestamp into something easier to read."""
    try:
        parsedDate = datetime.fromisoformat(isoTimestamp)
        return parsedDate.strftime("%d %b %Y, %H:%M")
    except (ValueError, TypeError):
        return isoTimestamp


def truncateCaption(caption, maxLength=70):
    """Shorten long captions for a clean one-line preview."""
    if not caption:
        return "(no caption)"

    singleLineCaption = caption.replace("\n", " ").strip()
    return textwrap.shorten(singleLineCaption, width=maxLength, placeholder="...")


def isWithinLast30Days(isoTimestamp):
    """Check whether a post's timestamp falls within the last 30 days."""
    try:
        postDate = datetime.fromisoformat(isoTimestamp)
    except (ValueError, TypeError):
        return False

    cutoffDate = datetime.now(timezone.utc) - timedelta(days=30)
    return postDate >= cutoffDate


def calculateEngagementRate(mediaItem, followersCount):
    """Calculate (likes + comments) / followers as a percentage."""
    if not followersCount:
        return 0

    likeCount = mediaItem.get("like_count", 0)
    commentsCount = mediaItem.get("comments_count", 0)
    return (likeCount + commentsCount) / followersCount * 100


def printPostSummary(postNumber, mediaItem, followersCount, insightValues):
    """Print one nicely formatted block for a single post."""
    likeCount = mediaItem.get("like_count", 0)
    commentsCount = mediaItem.get("comments_count", 0)
    engagementRate = calculateEngagementRate(mediaItem, followersCount)

    print(f"\n{'-' * 60}")
    print(f"POST {postNumber}: {mediaItem.get('media_product_type', mediaItem.get('media_type'))}")
    print(f"{'-' * 60}")
    print(f"  Posted:      {formatTimestamp(mediaItem.get('timestamp'))}")
    print(f"  Caption:     {truncateCaption(mediaItem.get('caption'))}")
    print(f"  Link:        {mediaItem.get('permalink')}")
    print()
    print(f"  Likes:              {likeCount:>6}")
    print(f"  Comments:           {commentsCount:>6}")
    print(f"  Engagement rate:    {engagementRate:>6.2f}%   (likes + comments / followers)")
    print()
    print("  Insights:")
    if insightValues:
        for metricName, metricValue in insightValues.items():
            print(f"    {metricName:<20} {metricValue}")
    else:
        print("    (no insight metrics returned for this post)")


def printPostsSummary(heading, mediaItems, insightsByMediaId, followersCount):
    """
    Print a summary block for a set of posts, e.g.:

      SUMMARY across 10 posts
      ============================================================
        Average engagement rate: 0.96%
        Highest engagement rate: 1.72%
        Lowest engagement rate:  0.36%
        ...plus totals for likes, comments, saves, shares, and interactions.
    """
    if not mediaItems:
        print(f"\n{'=' * 60}")
        print(heading)
        print(f"{'=' * 60}")
        print("  No posts to summarize.")
        return

    engagementRates = [calculateEngagementRate(item, followersCount) for item in mediaItems]

    totalLikes = sum(item.get("like_count", 0) for item in mediaItems)
    totalComments = sum(item.get("comments_count", 0) for item in mediaItems)

    # These come from the insights pulls, so they'll only be present for
    # posts where that particular metric was successfully returned.
    totalSaved = sum(
        insightsByMediaId.get(item["id"], {}).get("saved", 0) for item in mediaItems
    )
    totalShares = sum(
        insightsByMediaId.get(item["id"], {}).get("shares", 0) for item in mediaItems
    )
    totalInteractions = sum(
        insightsByMediaId.get(item["id"], {}).get("total_interactions", 0) for item in mediaItems
    )
    totalReach = sum(
        insightsByMediaId.get(item["id"], {}).get("reach", 0) for item in mediaItems
    )

    sortedByRate = sorted(zip(mediaItems, engagementRates), key=lambda pair: pair[1])
    lowestPost, lowestRate = sortedByRate[0]
    highestPost, highestRate = sortedByRate[-1]

    print(f"\n{'=' * 60}")
    print(heading)
    print(f"{'=' * 60}")
    print(f"  Posts counted:            {len(mediaItems)}")
    print(f"  Average engagement rate:  {sum(engagementRates) / len(engagementRates):.2f}%")
    print(f"  Highest engagement rate:  {highestRate:.2f}%  ({formatTimestamp(highestPost.get('timestamp'))})")
    print(f"  Lowest engagement rate:   {lowestRate:.2f}%  ({formatTimestamp(lowestPost.get('timestamp'))})")
    print()
    print(f"  Total likes:              {totalLikes}")
    print(f"  Total comments:           {totalComments}")
    print(f"  Total saves:              {totalSaved}")
    print(f"  Total shares:             {totalShares}")
    print(f"  Total interactions:       {totalInteractions}")
    print(f"  Combined reach (summed):  {totalReach}")
    print(f"    Note: combined reach sums each post's unique reach, so the")
    print(f"    same follower seeing multiple posts is counted more than once.")


def printLast30DaysOverview(accessToken, userId, followersCount):
    """
    Pull a larger batch of posts, filter to the last 30 days, and print a
    summary overview for that window - independent of the 10 detailed posts
    shown earlier in the script.
    """
    recentMediaItems = pullMediaWithinLast30Days(accessToken, userId)

    # Pull insights for each post in the 30-day window so the summary can
    # include saves/shares/interactions/reach, not just likes and comments.
    insightsByMediaId = {}
    for mediaItem in recentMediaItems:
        productType = mediaItem.get("media_product_type", "")
        insightsByMediaId[mediaItem["id"]] = pullMediaInsights(
            accessToken, mediaItem["id"], productType
        )

    printPostsSummary(
        f"LAST 30 DAYS OVERVIEW ({len(recentMediaItems)} posts)",
        recentMediaItems,
        insightsByMediaId,
        followersCount,
    )

    totalAccountReach, reachError = pullAccountReachLast30Days(accessToken, userId)
    if reachError:
        print(f"\n  Account-level 30-day reach: FAILED ({reachError})")
    else:
        print(f"\n  Account-level reach (last 30 days, summed daily): {totalAccountReach}")
        print("    Note: this sums daily unique-reach values, so someone reached")
        print("    on multiple days may be counted more than once - useful as a")
        print("    trend indicator rather than a precise unique-account total.")


def main():
    accessToken, userId = loadToken()

    profileData = pullProfile(accessToken, userId)
    followersCount = profileData.get("followers_count", 0)

    print(f"\n{'=' * 60}")
    print(f"@{profileData.get('username')}  |  {profileData.get('account_type')}")
    print(
        f"Followers: {followersCount}   "
        f"Following: {profileData.get('follows_count')}   "
        f"Posts: {profileData.get('media_count')}"
    )
    print(f"{'=' * 60}")

    mediaItems = pullRecentMedia(accessToken, userId, mediaLimit=DETAILED_POST_COUNT)

    if not mediaItems:
        print("\nNo media items returned - nothing to show.")
        return

    insightsByMediaId = {}
    for postNumber, mediaItem in enumerate(mediaItems, start=1):
        productType = mediaItem.get("media_product_type", "")
        insightValues = pullMediaInsights(accessToken, mediaItem["id"], productType)
        insightsByMediaId[mediaItem["id"]] = insightValues
        printPostSummary(postNumber, mediaItem, followersCount, insightValues)

    printPostsSummary(
        f"SUMMARY across {len(mediaItems)} posts",
        mediaItems,
        insightsByMediaId,
        followersCount,
    )

    printLast30DaysOverview(accessToken, userId, followersCount)


if __name__ == "__main__":
    main()