#!/usr/bin/env python3
"""Interactive setup wizard for the weekly schedule generator.

Uses a conversational approach powered by Claude to generate a personalized
config.yaml. Optionally pulls context from Open Brain if configured.

Usage:
    python setup.py            # generate config.yaml
    python setup.py --test     # generate config.test.yaml (for testing)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"
CONFIG_EXAMPLE_PATH = Path(__file__).parent / "config.example.yaml"

if "--test" in sys.argv:
    CONFIG_PATH = Path(__file__).parent / "config.test.yaml"
    sys.argv.remove("--test")

SETUP_SYSTEM_PROMPT = """\
You are a friendly setup assistant for a weekly household schedule generator.
Your job is to have a natural conversation to learn about someone's household,
then generate a config.yaml file for them.

WHAT YOU NEED TO LEARN:
1. **Adults in the household** — for EACH adult, learn:
   - Name and role (primary scheduler, partner, caregiver/au pair/nanny, etc.)
   - Work schedule: days, start/end times, commute, office location
   - Recurring activities: gym (how often, which days, what type), sports leagues,
     clubs, classes — use a consistent flow for each person
   - Weekend activities or routines
2. **Children** — for each child:
   - Name and age
   - Recurring activities (swim, music, sports, forest school, etc.) with day/time/location
   - Nap schedule and bedtime/wake time
3. **Recurring household events** — cleaner, coop/volunteer shifts, etc.
4. **Dinner rules** — who cooks which nights, any fixed nights
5. **Pets** — ask about pets LAST. If dog: walks/day, walker schedule.
   If cat: feeding schedule, any special care. Tailor questions to pet type.

CONVERSATION STYLE:
- Be warm, casual, and efficient — like a friend helping you set things up
- Ask 2-4 questions at a time, grouped by topic
- Don't ask about things you can infer (e.g., if someone works Mon-Fri, don't ask
  which days they're home on weekends)
- When you have enough information, say so and generate the config
- If the user mentions something you don't have a field for, include it as a "notes" field

WHEN GENERATING THE CONFIG:
- Output ONLY the YAML content inside a ```yaml code block
- Follow the exact structure of the reference config below
- Use lowercase for all names/keys
- For the caregiver schedule, calculate Friday as "balance" if they have weekly hours
- Include all fields even if using defaults
- Add helpful comments

REFERENCE CONFIG STRUCTURE:
```yaml
{example_config}
```

IMPORTANT:
- Treat ALL adults the same in terms of questions asked (work schedule, activities, etc.)
- Do NOT ask about dog walking as part of the adult questions — that belongs under pets
- For gym/fitness: ask if they work out, how often per week, any fixed days, type of workout
- For recurring activities: ask day, time, location for each one
- Always confirm the final config with the user before they save it
"""

OPEN_BRAIN_CONTEXT_PROMPT = """\
Here are recent notes from my Open Brain — these contain real information about
my household, family members, schedules, and routines. Use everything relevant
to pre-fill my config. Start by telling me what you learned from these notes
(names, roles, schedules, activities, kids, pets, etc.), then ask me to confirm
or correct anything, and fill in any gaps.

OPEN BRAIN NOTES:
{notes}

Based on these notes, tell me what you already know about my household and what
you still need to ask about.
"""


def get_open_brain_context() -> str | None:
    """Try to pull household-relevant notes from Open Brain."""
    mcp_url = os.getenv("OPEN_BRAIN_MCP_URL")
    if not mcp_url:
        return None

    try:
        from open_brain import _parse_thoughts, _is_meta_note
        import asyncio

        async def _fetch_household(url: str) -> list:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            all_results = []
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Pull recent notes and family-tagged notes
                    for list_args in [
                        {"days": 30, "limit": 20},
                        {"topic": "family", "limit": 10},
                        {"topic": "scheduling", "limit": 10},
                    ]:
                        try:
                            result = await session.call_tool("list_thoughts", list_args)
                            all_results.extend(_parse_thoughts(result))
                        except Exception:
                            pass

                    # Semantic search for household-relevant topics
                    for query in [
                        "weekly schedule household config",
                        "adults children pets household members",
                        "dinner rules meals cooking",
                        "recurring cleaner coop shifts",
                    ]:
                        try:
                            result = await session.call_tool("search_thoughts", {"query": query, "limit": 5})
                            all_results.extend(_parse_thoughts(result))
                        except Exception:
                            pass
            return all_results

        results = asyncio.run(_fetch_household(mcp_url))

        # Dedup and filter
        seen = set()
        unique = []
        for r in results:
            text = r.get("text", r.get("content", ""))
            key = text[:100].strip()
            if key and key not in seen and not _is_meta_note(text):
                seen.add(key)
                unique.append(r)

        if unique:
            formatted = "\n".join(f"- {n.get('text', n.get('content', ''))}" for n in unique[:20])
            return formatted
    except Exception as exc:
        print(f"  (Could not pull Open Brain notes: {exc})")
    return None


def build_system_prompt() -> str:
    """Build the system prompt with the example config embedded."""
    example = ""
    if CONFIG_EXAMPLE_PATH.exists():
        example = CONFIG_EXAMPLE_PATH.read_text()
    return SETUP_SYSTEM_PROMPT.format(example_config=example)


def chat(client: anthropic.Anthropic, messages: list[dict], system: str) -> str:
    """Send messages to Claude and return the response."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=system,
            messages=messages,
        )
        return response.content[0].text
    except anthropic.AuthenticationError:
        print("\n  ❌ Invalid API key. Check ANTHROPIC_API_KEY in your .env file.")
        print("  Get a key at https://console.anthropic.com/settings/keys")
        sys.exit(1)
    except anthropic.APIError as exc:
        print(f"\n  ❌ API error: {exc}")
        sys.exit(1)


def extract_yaml(text: str) -> str | None:
    """Extract YAML content from a ```yaml code block."""
    if "```yaml" in text:
        start = text.index("```yaml") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    return None


def main():
    print()
    print("🗓️  Weekly Schedule Generator — Setup")
    print("=" * 50)
    print()

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not found in .env")
        print("This setup wizard uses Claude to generate your config.")
        print()
        api_key = input("Paste your Anthropic API key (or set it in .env): ").strip()
        if not api_key:
            print("\nCan't run setup without an API key. See README.md for details.")
            sys.exit(1)

    if CONFIG_PATH.exists() and CONFIG_PATH.name != "config.test.yaml":
        print(f"  ⚠️  {CONFIG_PATH.name} already exists.")
        confirm = input("  Overwrite? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("\nSetup cancelled. Your existing config is unchanged.")
            sys.exit(0)
        print()

    client = anthropic.Anthropic(api_key=api_key)
    system = build_system_prompt()
    messages: list[dict] = []

    # Try Open Brain for context
    print("Checking for Open Brain notes...")
    ob_notes = get_open_brain_context()

    if ob_notes:
        print("  Found notes! Using them to pre-fill your setup.\n")
        first_message = (
            OPEN_BRAIN_CONTEXT_PROMPT.format(notes=ob_notes)
            + "\nLet's set up my household config. Start by asking me about the adults in my household."
        )
    else:
        print("  No Open Brain configured — no worries, we'll start from scratch.\n")
        first_message = "Let's set up my household config. Start by asking me about the adults in my household."

    messages.append({"role": "user", "content": first_message})

    print("I'll ask you a few questions about your household to generate")
    print("your config file. Type your answers naturally.\n")
    print("-" * 50)

    # Conversation loop
    while True:
        response = chat(client, messages, system)
        messages.append({"role": "assistant", "content": response})

        # Check if response contains a YAML block (config generated)
        yaml_content = extract_yaml(response)

        if yaml_content:
            # Print the text before the YAML block
            before_yaml = response[:response.index("```yaml")].strip()
            if before_yaml:
                print(f"\n{before_yaml}\n")

            # Validate the YAML
            try:
                parsed = yaml.safe_load(yaml_content)
            except yaml.YAMLError as exc:
                print(f"\n  ⚠️  Generated YAML had an error: {exc}")
                print("  Asking Claude to fix it...\n")
                messages.append({"role": "user", "content": f"The YAML had a parse error: {exc}. Please fix it and regenerate."})
                continue

            # Show the config for review
            print("=" * 50)
            print("  Here's your generated config:")
            print("=" * 50)
            print()
            print(yaml_content)
            print()
            print("=" * 50)

            feedback = input("\nLooks good? (yes to save, or type changes): ").strip()

            if feedback.lower() in ("yes", "y", "looks good", "save", "lgtm", ""):
                # Write the config
                header = (
                    "# Household configuration for the weekly schedule generator.\n"
                    "# Generated by setup.py — edit freely, this file is gitignored.\n"
                    "# Secrets (API keys, calendar IDs) live in .env.\n\n"
                )
                with open(CONFIG_PATH, "w") as f:
                    f.write(header)
                    f.write(yaml_content)
                    f.write("\n")

                print(f"\n  ✅ Config saved to {CONFIG_PATH}")
                print()
                print("  Next steps:")
                print("    1. Make sure .env has your API keys (see .env.example)")
                print("    2. Set up Google Calendar credentials (see README.md)")
                print("    3. Run: python generate_schedule.py")
                print()
                break
            else:
                # Send feedback back to Claude for revision
                messages.append({"role": "user", "content": feedback})
                continue
        else:
            # Regular conversation — print and prompt for input
            print(f"\n{response}\n")
            user_input = input("> ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("\nSetup cancelled.")
                sys.exit(0)

            messages.append({"role": "user", "content": user_input})


if __name__ == "__main__":
    main()
