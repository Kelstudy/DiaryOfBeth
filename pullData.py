"""
pullData.py

The real, automated data-collection script. Uses the shared pull logic in
igApi.py and packages everything into one JSON "snapshot" record, appended
to a running history file (data/statsHistory.json).

Each run adds one new entry to the history, which is what powers the growth
charts and "top posts" gallery on the frontend later. If a run's snapshot is
identical (aside from the timestamp) to the last saved one - e.g. the script
was re-run with nothing new to report - it is skipped instead of appended,
to keep the history free of no-op duplicates.

On start, it prompts for exactly one pull mode - "pull every post from the
last N days", "pull exactly N posts", or "pull every post since a given
date" - never combined, so asking for 30 days and 10 posts can't silently
cap you at 10 posts. The since-date mode treats the date as starting at
midnight UTC, so that date's own posts are included.

Passing --mode and --value skips the prompts entirely, for non-interactive
use (e.g. a GitHub Actions cron job, which has no terminal to type into):
  python pullData.py --mode days --value 30
  python pullData.py --mode posts --value 10
  python pullData.py --mode date --value 2026-07-01

Run interactively with:
  python pullData.py
"""

import argparse
import json
import os
from datetime import datetime, timezone

from igApi import (
    loadToken,
    pullProfile,
    pullMostRecentPosts,
    pullMediaInsights,
    pullMediaWithinLastNDays,
    pullMediaSinceDate,
    pullAccountReachLastNDays,
    pullAccountProfileViewsLastNDays,
    calculateEngagementRate,
    DEFAULT_POST_COUNT,
)

DATA_FILE_PATH = os.path.join("data", "statsHistory.json")
DEFAULT_WINDOW_DAYS = 30


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


def buildPulledSetSummary(mediaItems, insightsByMediaId, followersCount):
    """Aggregate totals across the pulled post set for storage."""
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


def daysSpannedByPosts(mediaItems, fallbackDays):
    """
    Estimate how many days the pulled posts span, for sizing the account-level
    reach query when pulling by post count rather than by day window (that
    endpoint needs a since/until range, not a post count).
    """
    if not mediaItems:
        return fallbackDays

    oldestTimestamp = min(mediaItems, key=lambda item: item.get("timestamp", "")).get("timestamp")
    try:
        oldestDate = datetime.fromisoformat(oldestTimestamp)
    except (ValueError, TypeError):
        return fallbackDays

    spanDays = (datetime.now(timezone.utc) - oldestDate).days + 1
    return max(spanDays, 1)


def buildSnapshot(accessToken, userId, pullMode, pullValue):
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

    if pullMode == "days":
        mediaItems = pullMediaWithinLastNDays(accessToken, userId, pullValue)
        reachWindowDays = pullValue
    elif pullMode == "date":
        cutoffDate = datetime.strptime(pullValue, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        mediaItems = pullMediaSinceDate(accessToken, userId, cutoffDate)
        reachWindowDays = max((datetime.now(timezone.utc) - cutoffDate).days + 1, 1)
    else:
        mediaItems = pullMostRecentPosts(accessToken, userId, pullValue)
        reachWindowDays = daysSpannedByPosts(mediaItems, fallbackDays=DEFAULT_WINDOW_DAYS)

    totalPosts = len(mediaItems)
    print(f"  Found {totalPosts} post(s) to pull - pulling insights for each...")

    insightsByMediaId = {}
    for postIndex, mediaItem in enumerate(mediaItems, start=1):
        productType = mediaItem.get("media_product_type", "")
        insightsByMediaId[mediaItem["id"]] = pullMediaInsights(
            accessToken, mediaItem["id"], productType
        )
        if postIndex % 10 == 0 or postIndex == totalPosts:
            print(f"    ...{postIndex}/{totalPosts} insight pulls done")

    postRecords = [
        buildPostRecord(mediaItem, followersCount, insightsByMediaId.get(mediaItem["id"], {}))
        for mediaItem in mediaItems
    ]

    pulledSetSummary = buildPulledSetSummary(mediaItems, insightsByMediaId, followersCount)
    pulledSetSummary["pullMode"] = pullMode
    pulledSetSummary["pullValue"] = pullValue

    totalAccountReach, reachError = pullAccountReachLastNDays(accessToken, userId, reachWindowDays)
    pulledSetSummary["accountReachWindowDays"] = reachWindowDays
    pulledSetSummary["accountReachSummed"] = totalAccountReach
    pulledSetSummary["accountReachError"] = reachError

    totalProfileViews, profileViewsError = pullAccountProfileViewsLastNDays(accessToken, userId, reachWindowDays)
    pulledSetSummary["profileViewsWindowDays"] = reachWindowDays
    pulledSetSummary["profileViews"] = totalProfileViews
    pulledSetSummary["profileViewsError"] = profileViewsError

    return {
        "pulledAt": datetime.now(timezone.utc).isoformat(),
        "profile": profileRecord,
        "recentPosts": postRecords,
        "pulledSetSummary": pulledSetSummary,
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


def promptForPositiveInt(promptText, defaultValue):
    """Ask for a positive integer, falling back to defaultValue on blank/invalid input."""
    rawInput = input(f"{promptText} [default {defaultValue}]: ").strip()

    if not rawInput:
        return defaultValue

    try:
        parsedValue = int(rawInput)
    except ValueError:
        print(f"  Not a whole number - using default of {defaultValue}.")
        return defaultValue

    if parsedValue <= 0:
        print(f"  Must be positive - using default of {defaultValue}.")
        return defaultValue

    return parsedValue


def promptForDateString(promptText):
    """Ask for a date in YYYY-MM-DD form, re-prompting until one parses."""
    while True:
        rawInput = input(f"{promptText} (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(rawInput, "%Y-%m-%d")
            return rawInput
        except ValueError:
            print("  Not a valid date - please use YYYY-MM-DD format (e.g. 2026-07-01).")


def promptForPullMode():
    """
    Ask the user to choose exactly one way to select posts: by day window
    (every post from the last N days), by post count (exactly N most recent
    posts, however far back that reaches), or by a since-date (every post
    from midnight UTC on that date onward). Returns (pullMode, pullValue).
    """
    print("How should posts be pulled?")
    print("  1) By number of days - pulls every post from that many days back")
    print("  2) By number of posts - pulls exactly that many most recent posts")
    print("  3) By date - pulls every post since midnight UTC on a given date")
    choice = input("Choose 1, 2, or 3 [default 1]: ").strip()

    if choice == "2":
        postCount = promptForPositiveInt("How many posts to pull?", DEFAULT_POST_COUNT)
        return "posts", postCount

    if choice == "3":
        dateString = promptForDateString("Pull every post since which date?")
        return "date", dateString

    windowDays = promptForPositiveInt("How many days to pull?", DEFAULT_WINDOW_DAYS)
    return "days", windowDays


def parseArgs():
    """Parse optional --mode/--value CLI args for non-interactive runs."""
    parser = argparse.ArgumentParser(description="Pull Instagram stats into data/statsHistory.json")
    parser.add_argument(
        "--mode",
        choices=["days", "posts", "date"],
        help="Pull mode. Requires --value. Omit both --mode and --value to be prompted interactively.",
    )
    parser.add_argument(
        "--value",
        help="Value for --mode: a positive integer for 'days'/'posts', or YYYY-MM-DD for 'date'.",
    )
    args = parser.parse_args()

    if bool(args.mode) != bool(args.value):
        parser.error("--mode and --value must be provided together.")

    return args


def resolvePullModeFromArgs(mode, rawValue):
    """Validate and convert CLI --mode/--value into (pullMode, pullValue), or exit with an error."""
    if mode == "date":
        try:
            datetime.strptime(rawValue, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"--value must be YYYY-MM-DD for --mode date, got: {rawValue!r}")
        return "date", rawValue

    try:
        parsedValue = int(rawValue)
    except ValueError:
        raise SystemExit(f"--value must be a whole number for --mode {mode}, got: {rawValue!r}")

    if parsedValue <= 0:
        raise SystemExit(f"--value must be positive for --mode {mode}, got: {parsedValue}")

    return mode, parsedValue


def main():
    accessToken, userId = loadToken()

    args = parseArgs()
    if args.mode:
        pullMode, pullValue = resolvePullModeFromArgs(args.mode, args.value)
    else:
        pullMode, pullValue = promptForPullMode()

    print("Pulling latest Instagram stats...")
    newSnapshot = buildSnapshot(accessToken, userId, pullMode, pullValue)

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
