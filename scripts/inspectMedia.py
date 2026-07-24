"""
inspectMedia.py

One-off diagnostic, not part of the automated pipeline. Pulls extended
fields (including is_shared_to_feed, which Meta's docs describe as
controlling whether a reel appears in the main Feed vs. only the Reels
tab) for the most recent posts, and flags clusters of posts published
within a few seconds of each other.

Those tight clusters are suspected "trial reels" - Instagram uploads
several variants near-simultaneously and only one gets promoted to the
real post, but all variants can show up in the /media API response.

This script does not change stored data or filter anything - it is a
one-time comparison tool. Run it, then compare is_shared_to_feed (and
any other fields that differ) between a clustered post and a normal,
isolated post to confirm which field reliably distinguishes trial
reels before adding filtering logic to igApi.py.

Run with:
  python inspectMedia.py
"""

import json
from datetime import datetime

import requests

from igApi import BASE_URL, loadToken

# Fields beyond what igApi.py normally pulls, to compare candidate posts.
INSPECT_FIELDS = (
    "id,caption,media_type,media_product_type,is_shared_to_feed,"
    "timestamp,permalink,like_count,comments_count"
)

CLUSTER_GAP_SECONDS = 60


def pullMediaDetailed(accessToken, userId, mediaLimit=25):
    response = requests.get(
        f"{BASE_URL}/{userId}/media",
        params={"fields": INSPECT_FIELDS, "limit": mediaLimit, "access_token": accessToken},
    )
    response.raise_for_status()
    return response.json().get("data", [])


def flagClusters(mediaItems):
    """Mark posts published within CLUSTER_GAP_SECONDS of the next-newest post."""
    parsedItems = []
    for item in mediaItems:
        try:
            postDate = datetime.fromisoformat(item["timestamp"])
        except (ValueError, TypeError, KeyError):
            postDate = None
        parsedItems.append((item, postDate))

    flagged = set()
    for index in range(len(parsedItems) - 1):
        currentItem, currentDate = parsedItems[index]
        nextItem, nextDate = parsedItems[index + 1]
        if currentDate and nextDate:
            gapSeconds = (currentDate - nextDate).total_seconds()
            if 0 <= gapSeconds <= CLUSTER_GAP_SECONDS:
                flagged.add(currentItem["id"])
                flagged.add(nextItem["id"])

    return flagged


def main():
    accessToken, userId = loadToken()
    mediaItems = pullMediaDetailed(accessToken, userId)

    clusteredIds = flagClusters(mediaItems)

    print(f"Pulled {len(mediaItems)} recent post(s). "
          f"{len(clusteredIds)} flagged as part of a same-minute cluster "
          f"(possible trial reel variants).\n")

    for item in mediaItems:
        marker = "  <-- CLUSTERED" if item["id"] in clusteredIds else ""
        print(json.dumps(item, indent=2) + marker)
        print("-" * 60)


if __name__ == "__main__":
    main()
