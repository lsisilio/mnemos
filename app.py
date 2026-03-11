import streamlit as st
import anthropic
import pydeck as pdk
import pandas as pd
import json
import re
import uuid
import os
from streamlit_js_eval import streamlit_js_eval

BIOGRAPHY_PATH = os.path.join(os.path.dirname(__file__), "biography.md")

# =============================================================================
# SECTION 1: Constants & Configuration
# =============================================================================


MODEL_NAME = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Mnemos, a warm and thoughtful biographer. Your role is to guide the user through their life story via friendly conversation and progressively write their personal biography.

RESPONSE FORMAT (mandatory every turn):

You MUST structure every response using these XML tags:

1. <biography_section> — emit ONLY when you have enough content for a coherent prose paragraph (at least one clear biographical fact):
<biography_section>
<title>SECTION TITLE</title>
<text>PROSE — past tense, third person using the subject's name and pronouns ("Leonardo was born...", "She studied...", "He moved to..."). No markdown, no bullet points, no headers. Pure narrative prose only.</text>
</biography_section>

2. <life_events> — emit ALWAYS, even if the array is empty:
<life_events>
[{"id":"unique_short_id","label":"brief label","year":YYYY,"month":M_or_null,"lat":NN.NNNN,"lon":NN.NNNN,"category":"birth|move|education|career|marriage|other"}]
</life_events>
Include ALL events mentioned in the conversation so far, with updated information. Use your geographic knowledge for lat/lon coordinates. If a place name is ambiguous, ask the user to clarify in your narrative instead of guessing.

3. <narrative> — emit ALWAYS:
<narrative>
Your conversational reply to the user. Be warm and curious. Ask one focused follow-up question to gather the next piece of their story. Keep it concise.
</narrative>

RULES:
- Always emit all three tags (biography_section is optional only if you don't yet have enough for a paragraph)
- life_events JSON must be valid — double-check brackets and quotes
- narrative should never repeat what the biography_section already says
- Each biography_section should cover a distinct life period or theme
- Biography text must always be third person (use the subject's name and he/she/they pronouns — never "you")
- When revising a section, rewrite it completely incorporating the user's feedback

Start by warmly greeting the user and asking for their full name and place of birth."""

CATEGORY_COLORS_PYDECK = {
    "birth":     [255, 100, 100, 200],
    "move":      [100, 150, 255, 200],
    "education": [100, 220, 150, 200],
    "career":    [255, 200, 50,  200],
    "marriage":  [220, 100, 220, 200],
    "other":     [180, 180, 180, 200],
}

CATEGORY_EMOJI = {
    "birth":     "🟥",
    "move":      "🔵",
    "education": "🟢",
    "career":    "🟡",
    "marriage":  "💜",
    "other":     "⚪",
}


# =============================================================================
# SECTION 2: Session State Initialization
# =============================================================================

def init_session_state():
    defaults = {
        "api_key": None,
        "messages": [],
        "bio_sections": [],
        "life_events": [],
        "viz_mode": "Map",
        "is_streaming": False,
        "revision_requested_for": None,
        "api_error": None,
        "balloons_fired": False,
        "mb_show_note": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# =============================================================================
# SECTION 3: Claude API Layer
# =============================================================================

@st.cache_resource
def get_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def call_claude(messages: list) -> str:
    """Call Claude with the full message history and return the raw response text."""
    client = get_client(st.session_state.api_key)

    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

    # Anthropic requires at least one message
    if not api_messages:
        api_messages = [{"role": "user", "content": "Hello, please start."}]

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=api_messages,
    ) as stream:
        chunks = []
        for chunk in stream.text_stream:
            chunks.append(chunk)
        return "".join(chunks)


def parse_claude_response(raw: str) -> dict:
    """Extract structured fields from Claude's XML-tagged response."""
    result = {
        "biography_section": None,
        "life_events": [],
        "narrative": raw,  # fallback: show raw if parsing fails
    }

    bio_match = re.search(
        r"<biography_section>\s*<title>(.*?)</title>\s*<text>(.*?)</text>\s*</biography_section>",
        raw, re.DOTALL
    )
    if bio_match:
        result["biography_section"] = {
            "title": bio_match.group(1).strip(),
            "text": bio_match.group(2).strip(),
        }

    events_match = re.search(
        r"<life_events>\s*(\[.*?\])\s*</life_events>",
        raw, re.DOTALL
    )
    if events_match:
        try:
            result["life_events"] = json.loads(events_match.group(1))
        except json.JSONDecodeError:
            pass

    narrative_match = re.search(
        r"<narrative>(.*?)</narrative>",
        raw, re.DOTALL
    )
    if narrative_match:
        result["narrative"] = narrative_match.group(1).strip()

    return result


# =============================================================================
# SECTION 4: State Mutation Helpers
# =============================================================================

def add_bio_section(title: str, text: str):
    """Add a new biography section, or replace the one being revised."""
    if st.session_state.revision_requested_for:
        for i, s in enumerate(st.session_state.bio_sections):
            if s["id"] == st.session_state.revision_requested_for:
                st.session_state.bio_sections[i] = {
                    "id": s["id"],
                    "title": title,
                    "text": text,
                    "status": "pending",
                    "revision_note": None,
                }
                return
    st.session_state.bio_sections.append({
        "id": str(uuid.uuid4()),
        "title": title,
        "text": text,
        "status": "pending",
        "revision_note": None,
    })


def update_bio_section_status(section_id: str, status: str, revision_note=None):
    for section in st.session_state.bio_sections:
        if section["id"] == section_id:
            section["status"] = status
            section["revision_note"] = revision_note
            break


def upsert_life_events(events: list):
    existing_ids = {e["id"] for e in st.session_state.life_events}
    for event in events:
        eid = event.get("id")
        if eid not in existing_ids:
            st.session_state.life_events.append(event)
            existing_ids.add(eid)
        else:
            for i, e in enumerate(st.session_state.life_events):
                if e["id"] == eid:
                    st.session_state.life_events[i] = event
                    break


def save_biography_md():
    """Write all approved sections to biography.md in the project root."""
    approved = [s for s in st.session_state.bio_sections if s["status"] == "approved"]
    if not approved:
        return
    lines = ["# Biography\n"]
    for s in approved:
        lines.append(f"## {s['title']}\n{s['text']}\n")
    with open(BIOGRAPHY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def inject_revision_message(section_id: str, revision_note: str):
    section = next((s for s in st.session_state.bio_sections if s["id"] == section_id), None)
    if not section:
        return
    revision_prompt = (
        f"Please revise the biography section titled '{section['title']}'. "
        f"Here is what needs to change: {revision_note}\n\n"
        f"Original text:\n{section['text']}"
    )
    st.session_state.messages.append({
        "role": "user",
        "content": revision_prompt,
        "display_text": f"_(Revision request for \"{section['title']}\")_ {revision_note}",
    })
    st.session_state.is_streaming = True
    st.session_state.revision_requested_for = section_id


# =============================================================================
# SECTION 5: Left Panel — Visualization
# =============================================================================

def render_map_panel():
    events = st.session_state.life_events
    if not events:
        st.caption("Locations will appear here as you share your story.")
        return

    df = pd.DataFrame(events).dropna(subset=["lat", "lon"])
    if df.empty:
        st.caption("No location data yet.")
        return

    df["color"] = df["category"].map(
        lambda c: CATEGORY_COLORS_PYDECK.get(c, CATEGORY_COLORS_PYDECK["other"])
    )

    center_lat = df["lat"].mean()
    center_lon = df["lon"].mean()
    zoom = 1 if len(df) > 5 else (2 if len(df) > 2 else 4)

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius=25000,
        pickable=True,
        auto_highlight=True,
    )

    df_sorted = df.sort_values("year")
    if len(df_sorted) > 1:
        path_data = [{"path": df_sorted[["lon", "lat"]].values.tolist()}]
        path_layer = pdk.Layer(
            "PathLayer",
            data=path_data,
            get_path="path",
            get_color=[100, 100, 200, 140],
            get_width=3,
            width_min_pixels=2,
        )
        layers = [path_layer, scatter_layer]
    else:
        layers = [scatter_layer]

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
    )

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={"text": "{label}\n{year}"},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )
    st.pydeck_chart(deck, use_container_width=True)


def render_timeline_panel():
    events = st.session_state.life_events
    if not events:
        st.caption("Life events will appear here as you share your story.")
        return

    df = pd.DataFrame(events).sort_values("year")
    with st.container(height=500, border=False):
        for _, row in df.iterrows():
            emoji = CATEGORY_EMOJI.get(row["category"], "⚪")
            year = int(row["year"])
            st.markdown(f"{emoji} **{year}** — {row['label']}")
            st.divider()


def render_viz_panel(key_prefix=""):
    mode = st.radio(
        "View",
        ["Map", "Timeline"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"{key_prefix}viz_mode_radio",
        index=["Map", "Timeline"].index(st.session_state.viz_mode),
    )
    st.session_state.viz_mode = mode
    with st.container(height=480, border=False):
        if mode == "Map":
            render_map_panel()
        else:
            render_timeline_panel()


# =============================================================================
# SECTION 6: Middle Panel — Chat
# =============================================================================

def render_api_key_entry():
    if not st.session_state.api_key:
        key = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            help="Your key is stored only in this browser session and never sent anywhere except Anthropic's API.",
        )
        if key:
            st.session_state.api_key = key
            st.rerun()
    else:
        st.caption("API key active")


def handle_claude_response():
    """Called when is_streaming is True. Calls Claude, parses, updates state."""
    try:
        raw = call_claude(st.session_state.messages)
    except anthropic.AuthenticationError:
        st.session_state.api_error = "Invalid API key. Please check your key and try again."
        st.session_state.is_streaming = False
        return
    except anthropic.PermissionDeniedError:
        st.session_state.api_error = "API key has no credits or insufficient permissions. Add credits at console.anthropic.com."
        st.session_state.is_streaming = False
        return
    except anthropic.APIStatusError as e:
        st.session_state.api_error = f"API error ({e.status_code}): {e.message}"
        st.session_state.is_streaming = False
        return
    except Exception as e:
        st.session_state.api_error = f"Unexpected error: {str(e)}"
        st.session_state.is_streaming = False
        return

    st.session_state.api_error = None
    parsed = parse_claude_response(raw)

    st.session_state.messages.append({
        "role": "assistant",
        "content": raw,
        "display_text": parsed["narrative"],
    })

    if parsed["biography_section"]:
        add_bio_section(
            title=parsed["biography_section"]["title"],
            text=parsed["biography_section"]["text"],
        )

    if parsed["life_events"]:
        upsert_life_events(parsed["life_events"])

    st.session_state.is_streaming = False
    st.session_state.revision_requested_for = None


def render_chat_panel(show_mobile_actions=False):
    st.subheader("Your Story")
    render_api_key_entry()

    has_key = bool(st.session_state.api_key)

    if st.session_state.api_error:
        st.error(st.session_state.api_error)

    # Trigger first greeting if chat is empty and we have a key
    if has_key and not st.session_state.messages and not st.session_state.is_streaming:
        st.session_state.is_streaming = True

    # Handle streaming (Claude call) before rendering chat history
    if st.session_state.is_streaming and has_key:
        with st.spinner("Mnemos is writing..."):
            handle_claude_response()
        st.rerun()

    # Chat history
    chat_container = st.container(height=400, border=False)
    with chat_container:
        for msg in st.session_state.messages:
            display = msg.get("display_text", msg["content"])
            with st.chat_message(msg["role"]):
                st.markdown(display)

    # Input
    user_input = st.chat_input(
        "Tell me about your life...",
        disabled=not has_key or st.session_state.is_streaming,
    )
    if user_input:
        st.session_state.messages.append({
            "role": "user",
            "content": user_input,
            "display_text": user_input,
        })
        st.session_state.is_streaming = True
        st.rerun()

    if show_mobile_actions:
        active_sections = [s for s in st.session_state.bio_sections if s["status"] in ("pending", "rejected")]
        approved_sections = [s for s in st.session_state.bio_sections if s["status"] == "approved"]
        if active_sections:
            if st.button("📝 Review new section", use_container_width=True, key="mobile_review"):
                show_review_dialog()
        if approved_sections:
            if st.button("Finish biography", use_container_width=True, key="mobile_finish", type="primary"):
                show_completion_dialog()


# =============================================================================
# SECTION 7: Right Panel — Biography
# =============================================================================

@st.dialog("Review Section", width="large")
def show_review_dialog():
    active = [s for s in st.session_state.bio_sections if s["status"] in ("pending", "rejected")]
    if not active:
        st.info("No sections pending review.")
        return
    section = active[0]
    sid = section["id"]
    st.markdown(f"### {section['title']}")
    st.markdown(section["text"])
    st.divider()

    col_a, col_r = st.columns(2)
    with col_a:
        if st.button("Approve", key="mb_approve", type="primary", use_container_width=True):
            update_bio_section_status(sid, "approved")
            save_biography_md()
            st.session_state["mb_show_note"] = False
            st.rerun()
    with col_r:
        if st.button("Revise", key="mb_revise", use_container_width=True):
            st.session_state["mb_show_note"] = True
            st.rerun()

    if st.session_state.get("mb_show_note"):
        note = st.text_area(
            "What should change?",
            key="mb_note",
            placeholder="e.g. Make it warmer / fix the dates",
        )
        if st.button("Send for revision", key="mb_send_revision", type="primary"):
            update_bio_section_status(sid, "rejected", revision_note=note)
            inject_revision_message(sid, note)
            st.session_state["mb_show_note"] = False
            st.rerun()


@st.dialog("Your Biography", width="large")
def show_completion_dialog():
    if not st.session_state.balloons_fired:
        st.balloons()
        st.session_state.balloons_fired = True

    approved = [s for s in st.session_state.bio_sections if s["status"] == "approved"]
    st.markdown("### Your biography is complete! 🎉")
    st.divider()
    for s in approved:
        st.markdown(f"### {s['title']}")
        st.markdown(s["text"])
        st.divider()

    md_content = "# Biography\n\n" + "\n\n".join(
        f"## {s['title']}\n{s['text']}" for s in approved
    )
    col_dl, col_edit = st.columns(2)
    with col_dl:
        st.download_button(
            "Download (.md)",
            data=md_content,
            file_name="biography.md",
            mime="text/markdown",
            use_container_width=True,
            type="primary",
        )
    with col_edit:
        if st.button("Keep editing", use_container_width=True):
            st.session_state.balloons_fired = False
            st.rerun()


def render_bio_panel(key_prefix=""):
    st.subheader("Biography")

    approved = [s for s in st.session_state.bio_sections if s["status"] == "approved"]
    active = [s for s in st.session_state.bio_sections if s["status"] in ("pending", "rejected")]

    # Download button (only when there's something approved)
    if approved:
        md_content = "# Biography\n\n" + "\n\n".join(
            f"## {s['title']}\n{s['text']}" for s in approved
        )
        st.download_button(
            "Download biography (.md)",
            data=md_content,
            file_name="biography.md",
            mime="text/markdown",
            use_container_width=True,
            key=f"{key_prefix}dl_bio",
        )

    # Approved document zone — scrollable, continuous prose
    if approved:
        with st.container(height=300, border=False):
            for s in approved:
                st.markdown(f"### {s['title']}")
                st.markdown(s["text"])
                st.divider()

    # Pending / rejected card — single section, always visible below
    if active:
        section = active[0]
        sid = section["id"]
        status = section["status"]

        with st.container(border=True):
            st.markdown(f"**{section['title']}**")
            st.markdown(section["text"])

            if status == "pending":
                col_a, col_r = st.columns(2)
                with col_a:
                    if st.button("Approve", key=f"{key_prefix}approve_{sid}", type="primary", use_container_width=True):
                        update_bio_section_status(sid, "approved")
                        save_biography_md()
                        st.rerun()
                with col_r:
                    if st.button("Revise", key=f"{key_prefix}reject_{sid}", use_container_width=True):
                        st.session_state[f"{key_prefix}show_revision_{sid}"] = True
                        st.rerun()

                if st.session_state.get(f"{key_prefix}show_revision_{sid}"):
                    note = st.text_area(
                        "What should change?",
                        key=f"{key_prefix}note_{sid}",
                        placeholder="e.g. Make it warmer / add more detail about school years / fix the dates",
                    )
                    if st.button("Send for revision", key=f"{key_prefix}send_revision_{sid}", type="primary"):
                        update_bio_section_status(sid, "rejected", revision_note=note)
                        inject_revision_message(sid, note)
                        del st.session_state[f"{key_prefix}show_revision_{sid}"]
                        st.rerun()

            elif status == "rejected":
                st.warning(f"Revision requested: {section.get('revision_note') or ''}")

    elif not approved:
        st.caption("Your biography will appear here as we talk.")
    else:
        st.caption("Keep chatting — the next section will appear here.")

    if approved:
        st.markdown("---")
        if st.button("Finish biography", use_container_width=True, type="primary", key=f"{key_prefix}finish"):
            show_completion_dialog()


# =============================================================================
# SECTION 8: Main Layout
# =============================================================================

def main():
    st.set_page_config(
        page_title="Mnemos",
        page_icon="📖",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown("""
        <style>
        /* Desktop: hide sidebar and its toggle */
        @media (min-width: 769px) {
            section[data-testid="stSidebar"] { display: none !important; }
            button[data-testid="stSidebarCollapsedControl"] { display: none !important; }
        }
        /* Mobile: full-width sidebar only when open */
        @media (max-width: 768px) {
            section[data-testid="stSidebar"][aria-expanded="true"] {
                width: 100vw !important;
                min-width: 100vw !important;
            }
        }
        /* Shared */
        .main .block-container { padding-top: 1.2rem; padding-bottom: 0; }
        div[data-testid="column"] { padding: 0 0.4rem; }
        </style>
    """, unsafe_allow_html=True)

    init_session_state()

    screen_width = streamlit_js_eval(js_expressions='window.innerWidth', key='screen_width')
    is_mobile = bool(screen_width and screen_width < 769)

    # Sidebar — always rendered; visible only on mobile (CSS hides it on desktop)
    with st.sidebar:
        st.markdown("### Mnemos")
        render_viz_panel(key_prefix="sb_")
        st.divider()
        render_bio_panel(key_prefix="sb_")

    st.title("Mnemos")
    st.caption("AI-powered biography builder")

    if is_mobile:
        render_chat_panel(show_mobile_actions=True)
    else:
        col_left, col_mid, col_right = st.columns([1.2, 1.8, 1.0], gap="small")
        with col_left:
            render_viz_panel()
        with col_mid:
            render_chat_panel(show_mobile_actions=False)
        with col_right:
            render_bio_panel()


if __name__ == "__main__":
    main()
