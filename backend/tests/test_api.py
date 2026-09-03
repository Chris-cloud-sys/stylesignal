"""API contract tests — spec §6, plus the §1 quota rules.

The VLM is off in the suite, so uploads exercise the §7.6 fallback path
end-to-end: upload → pending → worker → complete.
"""
import time
import uuid

import pytest

from .conftest import make_jpeg

POLL_TIMEOUT_SECONDS = 20


def wait_for_terminal(client, outfit_id: str) -> dict:
    """§6.6: poll until the outfit reaches a terminal status."""
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    payload = {}
    while time.time() < deadline:
        response = client.get("/v1/outfits/{0}".format(outfit_id))
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in ("complete", "failed"):
            return payload
        time.sleep(0.25)
    raise AssertionError(
        "outfit {0} never settled; last status={1}".format(
            outfit_id, payload.get("status")
        )
    )


def upload(client, **form) -> dict:
    response = client.post(
        "/v1/outfits",
        files={"image": ("outfit.jpg", make_jpeg(), "image/jpeg")},
        data=form,
    )
    assert response.status_code == 202, response.text
    return response.json()


# --- Health + auth ---------------------------------------------------------
def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["queue"] == "inprocess"
    assert body["vlm_enabled"] is False


def test_register_login_refresh_me(client):
    email = "flow-{0}@example.com".format(uuid.uuid4().hex[:8])

    registered = client.post(
        "/v1/auth/register", json={"email": email, "password": "a-long-password"}
    )
    assert registered.status_code == 201
    tokens = registered.json()

    logged_in = client.post(
        "/v1/auth/login", json={"email": email, "password": "a-long-password"}
    )
    assert logged_in.status_code == 200

    refreshed = client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200

    me = client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer {0}".format(refreshed.json()["access_token"])},
    )
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == email
    assert body["quota"]["plan"] == "free"
    assert body["quota"]["scans_remaining"] == 3


def test_duplicate_registration_is_rejected(client):
    email = "dupe-{0}@example.com".format(uuid.uuid4().hex[:8])
    payload = {"email": email, "password": "a-long-password"}
    assert client.post("/v1/auth/register", json=payload).status_code == 201

    conflict = client.post("/v1/auth/register", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "email_taken"


def test_bad_password_is_unauthorized(client):
    email = "wrong-{0}@example.com".format(uuid.uuid4().hex[:8])
    client.post("/v1/auth/register", json={"email": email, "password": "a-long-password"})

    response = client.post(
        "/v1/auth/login", json={"email": email, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_protected_routes_require_a_token(client):
    client.headers.pop("Authorization", None)
    response = client.get("/v1/outfits")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# --- §6.1 / §6.2 upload and poll ------------------------------------------
def test_upload_poll_and_read_feedback(auth_client):
    created = upload(auth_client, occasion="work", context_note="Client meeting")
    assert created["status"] == "pending"

    result = wait_for_terminal(auth_client, created["outfit_id"])
    assert result["status"] == "complete", result

    # §6.2 response shape
    assert result["occasion"] == "work"
    assert result["thumb_url"]
    assert "garments" in result
    feedback = result["feedback"]

    # §7.7 glanceable fields — always visible, top-level.
    assert feedback["verdict_phrase"].strip()
    assert feedback["verdict_subtitle"].strip()
    assert feedback["palette"], "whole-image palette runs regardless of detection"
    assert 2 <= len(feedback["quick_reads"]) <= 4
    for quick_read in feedback["quick_reads"]:
        assert quick_read["dimension"]
        assert quick_read["text"].strip()
    # The VLM is disabled in tests (conftest.py), so detection never runs and
    # no garments are ever found — meaning formality has no mean, so both
    # meters are correctly absent rather than a fabricated "strong"/"off".
    # test_rules.py covers the populated case directly. The endpoint uses
    # response_model_exclude_none=True, so a None field is omitted from the
    # JSON entirely rather than sent as null — hence .get(), not [...].
    assert feedback.get("occasion_match") is None
    assert feedback.get("signal_clarity") is None
    assert feedback.get("focal_point") is None

    # §7.7 long-form fields, now nested under full_read.
    full_read = feedback["full_read"]
    for field in ("overall_read", "color_note", "formality_note"):
        assert full_read[field].strip()

    # §7.3: nothing user-visible carries a score.
    assert not any(ch.isdigit() for ch in full_read["overall_read"])
    assert not any(ch.isdigit() for ch in feedback["verdict_phrase"])


def test_pending_response_is_minimal(auth_client):
    """§6.2: a pending outfit returns status only — no null-filled fields."""
    created = upload(auth_client)
    body = auth_client.get("/v1/outfits/{0}".format(created["outfit_id"])).json()
    assert body["outfit_id"] == created["outfit_id"]
    assert "feedback" not in body
    assert "failure_reason" not in body
    wait_for_terminal(auth_client, created["outfit_id"])


def test_invalid_occasion_is_rejected(auth_client):
    response = auth_client.post(
        "/v1/outfits",
        files={"image": ("o.jpg", make_jpeg(), "image/jpeg")},
        data={"occasion": "brunch-with-the-in-laws"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_occasion"


def test_capture_mode_defaults_to_worn(auth_client):
    result = wait_for_terminal(auth_client, upload(auth_client)["outfit_id"])
    assert result["capture_mode"] == "worn"


def test_item_capture_mode_is_persisted(auth_client):
    result = wait_for_terminal(
        auth_client, upload(auth_client, capture_mode="item")["outfit_id"]
    )
    assert result["capture_mode"] == "item"


def test_invalid_capture_mode_is_rejected(auth_client):
    response = auth_client.post(
        "/v1/outfits",
        files={"image": ("o.jpg", make_jpeg(), "image/jpeg")},
        data={"capture_mode": "on-a-cat"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_capture_mode"


def test_reread_inherits_the_source_outfits_capture_mode(auth_client):
    source = upload(auth_client, occasion="work", capture_mode="item")
    wait_for_terminal(auth_client, source["outfit_id"])

    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(source["outfit_id"]),
        json={"occasion": "evening"},
    ).json()
    result = wait_for_terminal(auth_client, reread["outfit_id"])
    assert result["capture_mode"] == "item"


def test_non_image_upload_is_rejected(auth_client):
    response = auth_client.post(
        "/v1/outfits",
        files={"image": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_context_note_length_is_enforced(auth_client):
    response = auth_client.post(
        "/v1/outfits",
        files={"image": ("o.jpg", make_jpeg(), "image/jpeg")},
        data={"context_note": "x" * 281},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_note_too_long"


def test_undecodable_image_fails_with_a_typed_reason(auth_client):
    """§4.3 / §5.3: junk bytes must produce ``undecodable``, not a 500."""
    response = auth_client.post(
        "/v1/outfits",
        files={"image": ("broken.jpg", b"\xff\xd8not-really-a-jpeg", "image/jpeg")},
    )
    assert response.status_code == 202

    result = wait_for_terminal(auth_client, response.json()["outfit_id"])
    assert result["status"] == "failed"
    assert result["failure_reason"] == "undecodable"


# --- §6.3 history ----------------------------------------------------------
def test_history_lists_newest_first_and_paginates(auth_client):
    created = [upload(auth_client)["outfit_id"] for _ in range(3)]
    for outfit_id in created:
        wait_for_terminal(auth_client, outfit_id)

    page = auth_client.get("/v1/outfits?limit=2").json()
    assert len(page["items"]) == 2
    assert page["cursor"]
    assert page["items"][0]["outfit_id"] == created[-1]

    second = auth_client.get(
        "/v1/outfits?limit=2&cursor={0}".format(page["cursor"])
    ).json()
    first_page_ids = {item["outfit_id"] for item in page["items"]}
    assert not first_page_ids & {item["outfit_id"] for item in second["items"]}


def test_bad_cursor_is_a_clean_400(auth_client):
    response = auth_client.get("/v1/outfits?cursor=not-a-cursor")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


# --- §6.4 delete + ownership ----------------------------------------------
def test_delete_soft_deletes_and_hides(auth_client):
    outfit_id = upload(auth_client)["outfit_id"]
    wait_for_terminal(auth_client, outfit_id)

    assert auth_client.delete("/v1/outfits/{0}".format(outfit_id)).status_code == 204
    assert auth_client.get("/v1/outfits/{0}".format(outfit_id)).status_code == 404

    listed = auth_client.get("/v1/outfits").json()["items"]
    assert outfit_id not in {item["outfit_id"] for item in listed}


def test_another_users_outfit_is_a_404_not_a_403(client):
    """Do not confirm that an id exists to someone who does not own it."""
    first = client.post(
        "/v1/auth/register",
        json={"email": "owner-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + first["access_token"]})
    outfit_id = upload(client)["outfit_id"]
    wait_for_terminal(client, outfit_id)

    second = client.post(
        "/v1/auth/register",
        json={"email": "other-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + second["access_token"]})

    assert client.get("/v1/outfits/{0}".format(outfit_id)).status_code == 404
    assert client.delete("/v1/outfits/{0}".format(outfit_id)).status_code == 404


# --- §1 quota + §8 cost control -------------------------------------------
def test_free_tier_allowance_is_enforced(auth_client):
    """Free tier is 3 scans in the test config."""
    for _ in range(3):
        upload(auth_client)

    blocked = auth_client.post(
        "/v1/outfits", files={"image": ("o.jpg", make_jpeg(), "image/jpeg")}
    )
    assert blocked.status_code == 402
    body = blocked.json()["error"]
    assert body["code"] == "quota_exceeded"
    assert body["details"]["scans_used_this_month"] == 3


def test_image_hash_cache_reuses_a_prior_scan(auth_client):
    """§8: the same pixels in the same context must not pay for a second run."""
    identical = make_jpeg(800, 1200, colour=(31, 61, 91))

    first = auth_client.post(
        "/v1/outfits",
        files={"image": ("a.jpg", identical, "image/jpeg")},
        data={"occasion": "evening"},
    ).json()
    wait_for_terminal(auth_client, first["outfit_id"])

    second = auth_client.post(
        "/v1/outfits",
        files={"image": ("b.jpg", identical, "image/jpeg")},
        data={"occasion": "evening"},
    ).json()
    result = wait_for_terminal(auth_client, second["outfit_id"])

    assert result["status"] == "complete"
    first_body = auth_client.get("/v1/outfits/{0}".format(first["outfit_id"])).json()
    assert (
        result["feedback"]["full_read"]["overall_read"]
        == first_body["feedback"]["full_read"]["overall_read"]
    )


# --- Result-screen "change occasion & re-read" ------------------------------
def test_reread_produces_a_new_outfit_under_a_different_occasion(auth_client):
    source = upload(auth_client, occasion="work")
    wait_for_terminal(auth_client, source["outfit_id"])

    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(source["outfit_id"]),
        json={"occasion": "evening"},
    )
    assert reread.status_code == 202, reread.text
    reread_body = reread.json()
    assert reread_body["outfit_id"] != source["outfit_id"]

    result = wait_for_terminal(auth_client, reread_body["outfit_id"])
    assert result["status"] == "complete"
    assert result["occasion"] == "evening"


def test_reread_charges_the_free_tier_allowance(auth_client):
    """Not a free cache hit — see reread_outfit's docstring for why."""
    source = upload(auth_client, occasion="work")
    wait_for_terminal(auth_client, source["outfit_id"])

    before = auth_client.get("/v1/auth/me").json()["quota"]["scans_remaining"]
    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(source["outfit_id"]),
        json={"occasion": "evening"},
    )
    assert reread.status_code == 202, reread.text
    after = auth_client.get("/v1/auth/me").json()["quota"]["scans_remaining"]
    assert after == before - 1


def test_reread_requires_a_completed_source_outfit(auth_client):
    pending = upload(auth_client, occasion="work")
    # Don't wait for completion — reread while still pending.
    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(pending["outfit_id"]),
        json={"occasion": "evening"},
    )
    assert reread.status_code == 400
    assert reread.json()["error"]["code"] == "outfit_not_complete"
    wait_for_terminal(auth_client, pending["outfit_id"])


def test_reread_of_missing_outfit_is_404(auth_client):
    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(uuid.uuid4()),
        json={"occasion": "evening"},
    )
    assert reread.status_code == 404


def test_reread_does_not_inherit_is_public(auth_client):
    """Re-sharing to the community feed is a fresh decision each time."""
    source = upload(auth_client, occasion="work", is_public="true")
    wait_for_terminal(auth_client, source["outfit_id"])

    reread = auth_client.post(
        "/v1/outfits/{0}/reread".format(source["outfit_id"]),
        json={"occasion": "evening"},
    ).json()
    result = wait_for_terminal(auth_client, reread["outfit_id"])
    assert result["is_public"] is False


# --- §6.5 community loop ---------------------------------------------------
def test_feed_excludes_your_own_outfits(client):
    author = client.post(
        "/v1/auth/register",
        json={"email": "author-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})

    public = client.post(
        "/v1/outfits",
        files={"image": ("p.jpg", make_jpeg(700, 1100, (90, 30, 30)), "image/jpeg")},
        data={"is_public": "true"},
    ).json()
    wait_for_terminal(client, public["outfit_id"])

    own_feed = client.get("/v1/feed").json()["items"]
    assert public["outfit_id"] not in {item["outfit_id"] for item in own_feed}

    rater = client.post(
        "/v1/auth/register",
        json={"email": "rater-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + rater["access_token"]})

    feed = client.get("/v1/feed").json()["items"]
    assert public["outfit_id"] in {item["outfit_id"] for item in feed}

    rated = client.post(
        "/v1/outfits/{0}/ratings".format(public["outfit_id"]),
        json={"dimension": "coherence", "value": 4},
    )
    assert rated.status_code == 201
    assert rated.json()["quota"]["rating_credits"] >= 0

    # §6.5: repeat = update, and an update earns nothing.
    again = client.post(
        "/v1/outfits/{0}/ratings".format(public["outfit_id"]),
        json={"dimension": "coherence", "value": 2},
    )
    assert again.status_code == 201
    assert again.json()["scans_earned"] == 0


def test_private_outfits_never_reach_the_feed(client):
    author = client.post(
        "/v1/auth/register",
        json={"email": "priv-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})
    private = upload(client)  # is_public defaults to False
    wait_for_terminal(client, private["outfit_id"])

    rater = client.post(
        "/v1/auth/register",
        json={"email": "look-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + rater["access_token"]})

    feed_ids = {item["outfit_id"] for item in client.get("/v1/feed").json()["items"]}
    assert private["outfit_id"] not in feed_ids

    blocked = client.post(
        "/v1/outfits/{0}/ratings".format(private["outfit_id"]),
        json={"dimension": "coherence", "value": 5},
    )
    assert blocked.status_code == 404


def test_invalid_rating_dimension_is_rejected(auth_client):
    response = auth_client.post(
        "/v1/outfits/{0}/ratings".format(uuid.uuid4()),
        json={"dimension": "vibes", "value": 3},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_dimension"


def test_rating_value_is_bounded(auth_client):
    response = auth_client.post(
        "/v1/outfits/{0}/ratings".format(uuid.uuid4()),
        json={"dimension": "coherence", "value": 9},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Likes/favorites (SPEC+, no dislike) ------------------------------------
def test_liking_an_outfit_shows_up_in_the_feed_and_on_the_owners_view(client):
    author = client.post(
        "/v1/auth/register",
        json={"email": "liked-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})
    public = client.post(
        "/v1/outfits",
        files={"image": ("p.jpg", make_jpeg(700, 1100, (30, 90, 30)), "image/jpeg")},
        data={"is_public": "true"},
    ).json()
    wait_for_terminal(client, public["outfit_id"])

    liker = client.post(
        "/v1/auth/register",
        json={"email": "liker-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + liker["access_token"]})

    feed_before = {
        item["outfit_id"]: item for item in client.get("/v1/feed").json()["items"]
    }
    assert feed_before[public["outfit_id"]]["like_count"] == 0
    assert feed_before[public["outfit_id"]]["liked_by_me"] is False

    liked = client.post("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    assert liked.status_code == 201, liked.text
    assert liked.json() == {
        "outfit_id": public["outfit_id"],
        "liked": True,
        "like_count": 1,
    }

    # Liking again is idempotent — no duplicate, count stays 1.
    again = client.post("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    assert again.status_code == 201
    assert again.json()["like_count"] == 1

    feed_after = {
        item["outfit_id"]: item for item in client.get("/v1/feed").json()["items"]
    }
    assert feed_after[public["outfit_id"]]["like_count"] == 1
    assert feed_after[public["outfit_id"]]["liked_by_me"] is True

    # The owner sees the count on their own history and outfit detail —
    # OutfitDetail only ever exposes an aggregate like_count, never a list
    # of likers (no profile/follow system to make that meaningful yet).
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})
    detail = client.get("/v1/outfits/{0}".format(public["outfit_id"])).json()
    assert detail["like_count"] == 1

    history = client.get("/v1/outfits").json()["items"]
    own_row = next(item for item in history if item["outfit_id"] == public["outfit_id"])
    assert own_row["like_count"] == 1


def test_unlike_removes_the_like(client):
    author = client.post(
        "/v1/auth/register",
        json={"email": "unlike-a-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})
    public = client.post(
        "/v1/outfits",
        files={"image": ("p.jpg", make_jpeg(700, 1100, (30, 30, 90)), "image/jpeg")},
        data={"is_public": "true"},
    ).json()
    wait_for_terminal(client, public["outfit_id"])

    liker = client.post(
        "/v1/auth/register",
        json={"email": "unlike-b-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + liker["access_token"]})

    client.post("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    unliked = client.delete("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    assert unliked.status_code == 200
    assert unliked.json() == {
        "outfit_id": public["outfit_id"],
        "liked": False,
        "like_count": 0,
    }

    # Unliking something never liked is a no-op, not an error.
    again = client.delete("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    assert again.status_code == 200
    assert again.json()["like_count"] == 0


def test_cannot_like_your_own_outfit(auth_client):
    public = auth_client.post(
        "/v1/outfits",
        files={"image": ("p.jpg", make_jpeg(), "image/jpeg")},
        data={"is_public": "true"},
    ).json()
    wait_for_terminal(auth_client, public["outfit_id"])

    blocked = auth_client.post("/v1/outfits/{0}/likes".format(public["outfit_id"]))
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "cannot_like_own_outfit"


def test_cannot_like_a_private_outfit(client):
    author = client.post(
        "/v1/auth/register",
        json={"email": "priv-like-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + author["access_token"]})
    private = upload(client)  # is_public defaults to False
    wait_for_terminal(client, private["outfit_id"])

    other = client.post(
        "/v1/auth/register",
        json={"email": "priv-like-b-{0}@x.com".format(uuid.uuid4().hex[:8]), "password": "a-long-password"},
    ).json()
    client.headers.update({"Authorization": "Bearer " + other["access_token"]})

    blocked = client.post("/v1/outfits/{0}/likes".format(private["outfit_id"]))
    assert blocked.status_code == 404


# --- Media -----------------------------------------------------------------
def test_thumbnail_requires_a_valid_signature(auth_client):
    outfit_id = upload(auth_client)["outfit_id"]
    result = wait_for_terminal(auth_client, outfit_id)

    signed = result["thumb_url"]
    assert auth_client.get(signed).status_code == 200

    tampered = signed.split("?")[0] + "?token=0.deadbeef"
    assert auth_client.get(tampered).status_code == 403
