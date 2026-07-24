"""
pullData.py

The real, automated data-collection script. Uses the shared pull logic in
igApi.py and packages everything into one JSON "snapshot" record, appended
to a running history file (data/statsHistory.json).

This is what the GitHub Actions cron job will run on a schedule. Each run
adds one new entry to the history, which is what powers the growth charts
and "top posts" gallery on the frontend later. If a run's snapshot is
identical (aside from the timestamp) to the last saved one - e.g. the script
was re-run with nothing new to report - it is skipped instead of appended,
to keep the history free of no-op duplicates.

Run with:
  python pullData.py
"""

import json
import os
from datetime import datetime, timezone

from igApi import (
    loadToken,
    pullProfile,
    pullRecentMedia,
    pullMediaInsights,
    pullMediaWithinLast30Days,
    pullAccountReachLast30Days,
    calculateEngagementRate,
    DETAILED_POST_COUNT,
)

DATA_FILE_PATH = os.path.join("data", "statsHistory.json")


def buildPostRecord(mediaItem, followersCount, insightValues):
    """Turn one raw media item + its insights into a clean record for storage."""
    return {
        "id": mediaItem.get("id"),
        "mediaType": mediaItem.get("media_product_type", mediaItem.get("media_type")),
        "timestamp": mediaItem.get("timestamp"),
        "permalink": mediaItem.get("permalink"),
        "caption": mediaItem.get("caption"),
        "likeCount": mediaItem.get("like_count", 0),
        "commentsCount": mediaItem.get("comments_count", 0),
        "engagementRate": round(calculateEngagementRate(mediaItem, followersCount), 4),
        "insights": insightValues,
    }


def buildLast30DaysSummary(mediaItems, insightsByMediaId, followersCount):
    """Aggregate totals across the last-30-days post set for storage."""
    if not mediaItems:
        return {
            "postsCounted": 0,
            "averageEngagementRate": 0,
            "totalLikes": 0,
            "totalComments": 0,
            "totalSaved": 0,
            "totalShares": 0,
            "totalInteractions": 0,
            "combinedReach": 0,
        }

    engagementRates = [calculateEngagementRate(item, followersCount) for item in mediaItems]

    return {
        "postsCounted": len(mediaItems),
        "averageEngagementRate": round(sum(engagementRates) / len(engagementRates), 4),
        "totalLikes": sum(item.get("like_count", 0) for item in mediaItems),
        "totalComments": sum(item.get("comments_count", 0) for item in mediaItems),
        "totalSaved": sum(
            insightsByMediaId.get(item["id"], {}).get("saved", 0) for item in mediaItems
        ),
        "totalShares": sum(
            insightsByMediaId.get(item["id"], {}).get("shares", 0) for item in mediaItems
        ),
        "totalInteractions": sum(
            insightsByMediaId.get(item["id"], {}).get("total_interactions", 0)
            for item in mediaItems
        ),
        "combinedReach": sum(
            insightsByMediaId.get(item["id"], {}).get("reach", 0) for item in mediaItems
        ),
    }


def buildSnapshot(accessToken, userId):
    """Run all the pulls and assemble one complete snapshot record."""
    profileData = pullProfile(accessToken, userId)
    followersCount = profileData.get("followers_count", 0)

    profileRecord = {
        "username": profileData.get("username"),
        "accountType": profileData.get("account_type"),
        "followersCount": followersCount,
        "followingCount": profileData.get("follows_count"),
        "mediaCount": profileData.get("media_count"),
    }

    recentMediaItems = pullRecentMedia(accessToken, userId, mediaLimit=DETAILED_POST_COUNT)

    recentInsightsByMediaId = {}
    for mediaItem in recentMediaItems:
        productType = mediaItem.get("media_product_type", "")
        recentInsightsByMediaId[mediaItem["id"]] = pullMediaInsights(
            accessToken, mediaItem["id"], productType
        )

    recentPostRecords = [
        buildPostRecord(mediaItem, followersCount, recentInsightsByMediaId.get(mediaItem["id"], {}))
        for mediaItem in recentMediaItems
    ]

    last30DaysMediaItems = pullMediaWithinLast30Days(accessToken, userId)
    totalLast30DaysPosts = len(last30DaysMediaItems)
    print(f"  Found {totalLast30DaysPosts} post(s) in the last 30 days - pulling insights for each...")

    last30DaysInsightsByMediaId = {}
    for postIndex, mediaItem in enumerate(last30DaysMediaItems, start=1):
        productType = mediaItem.get("media_product_type", "")
        last30DaysInsightsByMediaId[mediaItem["id"]] = pullMediaInsights(
            accessToken, mediaItem["id"], productType
        )
        if postIndex % 10 == 0 or postIndex == totalLast30DaysPosts:
            print(f"    ...{postIndex}/{totalLast30DaysPosts} insight pulls done")

    last30DaysSummary = buildLast30DaysSummary(
        last30DaysMediaItems, last30DaysInsightsByMediaId, followersCount
    )

    totalAccountReach, reachError = pullAccountReachLast30Days(accessToken, userId)
    last30DaysSummary["accountReachSummed"] = totalAccountReach
    last30DaysSummary["accountReachError"] = reachError

    return {
        "pulledAt": datetime.now(timezone.utc).isoformat(),
        "profile": profileRecord,
        "recentPosts": recentPostRecords,
        "last30Days": last30DaysSummary,
    }


def loadExistingHistory(dataFilePath):
    """Load the existing history file, or start a fresh list if none exists."""
    if not os.path.exists(dataFilePath):
        return []

    with open(dataFilePath, "r") as historyFile:
        return json.load(historyFile)


def saveHistory(dataFilePath, historyRecords):
    """Write the full history list back to disk, creating the folder if needed."""
    os.makedirs(os.path.dirname(dataFilePath), exist_ok=True)

    with open(dataFilePath, "w") as historyFile:
        json.dump(historyRecords, historyFile, indent=2)


def isDuplicateOfLastSnapshot(newSnapshot, historyRecords):
    """
    Check whether newSnapshot carries no new information compared to the
    most recent saved snapshot - i.e. everything except "pulledAt" is
    identical. This catches accidental back-to-back re-runs (nothing
    changed since last pull) without ever discarding a run that captured
    real movement in followers, likes, or insights.
    """
    if not historyRecords:
        return False

    lastSnapshot = historyRecords[-1]

    comparableNew = {key: value for key, value in newSnapshot.items() if key != "pulledAt"}
    comparableLast = {key: value for key, value in lastSnapshot.items() if key != "pulledAt"}

    return comparableNew == comparableLast


def main():
    accessToken, userId = loadToken()

    print("Pulling latest Instagram stats...")
    newSnapshot = buildSnapshot(accessToken, userId)

    historyRecords = loadExistingHistory(DATA_FILE_PATH)

    if isDuplicateOfLastSnapshot(newSnapshot, historyRecords):
        print("No change since the last saved snapshot - skipping save to avoid a duplicate entry.")
        return

    historyRecords.append(newSnapshot)
    saveHistory(DATA_FILE_PATH, historyRecords)

    print(f"Snapshot saved. History file now has {len(historyRecords)} entr" +
          ("y" if len(historyRecords) == 1 else "ies") + f" at {DATA_FILE_PATH}")


if __name__ == "__main__":
    main()