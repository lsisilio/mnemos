# Mnemos

**An AI-powered biography builder for preserving family stories.**

---

## The story behind it

While researching my family tree, I realized how little information we have from our ancestors: the elders who lived those stories are gone, and almost nothing was written down. Sometimes we have birth records, rarely a photo or two, but nothing about who they really were or how they lived.

I built Mnemos to help myself and others with no affinity for writing to collect and organize life events. It's a simple tool you can sit down with alongside a grandparent, a parent, or even alone, and walk away with a real written record of their life, told in an organized manner.

---

## What it does

Mnemos guides a conversation through someone's life story using a curious AI interviewer. As you talk, it:

- **Writes biography sections** in flowing prose, which you can approve or ask to revise
- **Plots life events on an interactive map** — places they were born, grew up, moved to
- **Builds a timeline** of the key moments in their life
- **Exports a clean biography** as a Markdown file you can save, print, or share

The whole thing runs in a browser — no installs needed for the person being interviewed.

---

## Try it

> Live demo: _link coming soon_

---

## How to run it locally

**Requirements**
- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/)

**Install dependencies**

```bash
pip install streamlit anthropic pydeck pandas streamlit-js-eval
```

**Launch**

```bash
streamlit run app.py
```

Then open the URL shown in your terminal (usually `http://localhost:8501`).

---

## How to use it

1. **Enter your Anthropic API key** when prompted — it stays in your browser session only and is never stored
2. **Start chatting** — Mnemos will greet you and ask for a name and place of birth to begin
3. As the story unfolds, **biography sections appear on the right** — approve them to add to the biography, or request revisions
4. When you're done, click **Finish biography** to see the full text and download it as a `.md` file

Works on both desktop (full 3-column layout) and mobile (chat-first, with map and biography in the side menu).

---

## Tech stack

- [Streamlit](https://streamlit.io/) — UI framework
- [Anthropic Claude](https://www.anthropic.com/) (`claude-sonnet-4-6`) — AI interviewer
- [PyDeck](https://deckgl.readthedocs.io/) — interactive map
- [Pandas](https://pandas.pydata.org/) — data handling
- [streamlit-js-eval](https://github.com/aghasemi/streamlit_js_eval) — mobile detection
