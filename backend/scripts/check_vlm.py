"""Verify the Anthropic API key actually works.

    python scripts/check_vlm.py

Makes one small real call and reports what happened. Costs a fraction of a
cent. Run this before wondering why every scan is coming back as templated
fallback text (§7.6).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()

    if settings.vlm_disabled:
        print("STYLESIGNAL_VLM_DISABLED=true — the VLM is switched off in .env.")
        print("Every scan will return templated fallback text (spec §7.6).")
        return 1

    key = settings.anthropic_api_key
    if not key:
        print("No API key found.")
        print("Set STYLESIGNAL_ANTHROPIC_API_KEY in backend/.env, then re-run.")
        return 1

    # Never print the key. Fingerprint it so you can tell which one is loaded.
    print("Key loaded:   {0}...{1} ({2} chars)".format(key[:14], key[-4:], len(key)))
    print("Model:        {0}".format(settings.vlm_model))
    print("Calling the API...")

    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=60.0)
    try:
        response = client.messages.create(
            model=settings.vlm_model,
            max_tokens=1024,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: StyleSignal is connected.",
                }
            ],
        )
    except anthropic.AuthenticationError:
        print("\nFAILED — the key was rejected (401).")
        print("Check for a stray space or a truncated paste in backend/.env.")
        return 1
    except anthropic.PermissionDeniedError as exc:
        print("\nFAILED — key is valid but not permitted for this model (403).")
        print("  {0}".format(exc.message))
        print("Check your workspace has access to {0}.".format(settings.vlm_model))
        return 1
    except anthropic.NotFoundError:
        print("\nFAILED — model {0!r} not found (404).".format(settings.vlm_model))
        print("Check STYLESIGNAL_VLM_MODEL in backend/.env.")
        return 1
    except anthropic.APIStatusError as exc:
        print("\nFAILED — HTTP {0}: {1}".format(exc.status_code, exc.message))
        if exc.status_code == 400 and "credit" in str(exc.message).lower():
            print("This usually means the org has no API credit. Add billing.")
        return 1
    except anthropic.APIConnectionError:
        print("\nFAILED — could not reach the API. Check your network/proxy.")
        return 1

    text = next(
        (block.text for block in response.content if block.type == "text"), ""
    )
    usage = response.usage

    print("\nOK — the key works.")
    print("  Replied:    {0}".format(text.strip()[:80]))
    print("  Served by:  {0}".format(response.model))
    print(
        "  Tokens:     {0} in / {1} out".format(
            usage.input_tokens, usage.output_tokens
        )
    )
    print("\nStart the server and your scans will now use the real engine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
