import json
import os
import re
import time

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from supabase import create_client

from satyam_prompt import SATYAM_SYSTEM_PROMPT

load_dotenv()

# Provider -> (base_url, env var for key, suggested models)
PROVIDERS = {
    "Groq": (
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"],
    ),
    "OpenRouter": (
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        ["meta-llama/llama-3.3-70b-instruct"],
    ),
    "Together": (
        "https://api.together.xyz/v1",
        "TOGETHER_API_KEY",
        ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    ),
}
MAX_HISTORY = 20       # last N messages model ko bhejte hain
MAX_PROMPT_CHARS = 2000
RATE_MAX_MSGS = 15     # itne messages...
RATE_WINDOW_SEC = 60   # ...itne seconds me

st.set_page_config(page_title="Satyam", page_icon="🤝", layout="centered")


# ---------- Helpers ----------
def secret(name, default=""):
    """Pehle Streamlit secrets, phir .env / environment se value uthata hai."""
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


def check_rate_limit():
    now = time.time()
    times = [t for t in st.session_state.get("msg_times", []) if now - t < RATE_WINDOW_SEC]
    if len(times) >= RATE_MAX_MSGS:
        st.session_state.msg_times = times
        return False
    times.append(now)
    st.session_state.msg_times = times
    return True


def suno_button(text):
    """Browser ki awaaz se jawab sunata hai (dobara dabane pe rukta hai)."""
    spoken = re.sub(r"[*_`#>~|]", "", text)
    safe = json.dumps(spoken).replace("</", "<\\/")
    components.html(
        f"""
        <button id="b" style="font-family:sans-serif;font-size:14px;padding:6px 14px;
          border:1px solid #d0d0d0;border-radius:20px;background:#fff;cursor:pointer;">
          🔊 Suno</button>
        <script>
          const text = {safe};
          const b = document.getElementById('b');
          b.onclick = () => {{
            const s = window.speechSynthesis;
            if (s.speaking) {{ s.cancel(); b.innerText = '🔊 Suno'; return; }}
            const u = new SpeechSynthesisUtterance(text);
            u.lang = 'hi-IN';
            u.onend = () => {{ b.innerText = '🔊 Suno'; }};
            b.innerText = '⏹ Roko';
            s.speak(u);
          }};
        </script>
        """,
        height=44,
    )


# ---------- Supabase (har user ka apna client, share nahi hota) ----------
def get_sb():
    if "sb" not in st.session_state:
        url, key = secret("SUPABASE_URL"), secret("SUPABASE_KEY")
        if not url or not key:
            st.error("SUPABASE_URL aur SUPABASE_KEY secrets mein daal pehle bhai.")
            st.stop()
        st.session_state.sb = create_client(url, key)
    return st.session_state.sb


def list_chats():
    res = get_sb().table("chats").select("id,title").order("created_at", desc=True).execute()
    return res.data or []


def load_messages(chat_id):
    res = (
        get_sb()
        .table("messages")
        .select("role,content")
        .eq("chat_id", chat_id)
        .order("id")
        .execute()
    )
    return res.data or []


def create_chat(title):
    res = get_sb().table("chats").insert({"title": title[:40]}).execute()
    return res.data[0]["id"]


def save_messages(chat_id, rows):
    get_sb().table("messages").insert(
        [{"chat_id": chat_id, "role": r, "content": c} for r, c in rows]
    ).execute()


def delete_chat(chat_id):
    get_sb().table("chats").delete().eq("id", chat_id).execute()


# ---------- Login / Signup ----------
def auth_screen():
    st.title("Satyam 🤝")
    st.caption("Tera AI dost, jo seedha aur sahi jawab de")
    tab_login, tab_signup = st.tabs(["Login", "Signup"])
    sb = get_sb()

    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login", type="primary"):
            if not email or not password:
                st.warning("Email aur password dono daal bhai.")
            else:
                try:
                    res = sb.auth.sign_in_with_password(
                        {"email": email.strip(), "password": password}
                    )
                    st.session_state.user = res.user
                    st.rerun()
                except Exception:
                    st.error("Email ya password galat hai bhai 😅")

    with tab_signup:
        email = st.text_input("Email", key="su_email")
        password = st.text_input("Password (kam se kam 6 akshar)", type="password", key="su_pw")
        if st.button("Account bana"):
            if not email or len(password) < 6:
                st.warning("Sahi email daal aur password kam se kam 6 akshar ka rakh.")
            else:
                try:
                    res = sb.auth.sign_up({"email": email.strip(), "password": password})
                    if res.session:  # email confirm band hai toh seedha login
                        st.session_state.user = res.user
                        st.rerun()
                    else:
                        st.success(
                            "Account ban gaya! Email pe confirm link aaya hoga, "
                            "usse confirm karke login kar."
                        )
                except Exception as e:
                    st.error(f"Signup nahi hua: {e}")


if "user" not in st.session_state:
    auth_screen()
    st.stop()

# ---------- Main app ----------
st.title("Satyam 🤝")
st.caption("Tera AI dost, jo seedha aur sahi jawab de")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_id" not in st.session_state:
    st.session_state.chat_id = None  # None = nayi chat, pehle message pe ban jayegi

# ---------- Sidebar ----------
with st.sidebar:
    st.caption(f"👤 {st.session_state.user.email}")

    if st.button("➕ Nayi chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_id = None
        st.rerun()

    st.subheader("Purani chats")
    try:
        chats = list_chats()
    except Exception as e:
        chats = []
        st.error(f"Chats load nahi hui: {e}")

    if not chats:
        st.caption("Abhi koi chat nahi hai. Pehla message bhej! 😉")

    for c in chats:
        col1, col2 = st.columns([5, 1])
        is_open = c["id"] == st.session_state.chat_id
        if col1.button(
            ("▶ " if is_open else "") + c["title"],
            key=f"open_{c['id']}",
            use_container_width=True,
        ):
            st.session_state.chat_id = c["id"]
            st.session_state.messages = load_messages(c["id"])
            st.rerun()
        if col2.button("🗑", key=f"del_{c['id']}"):
            delete_chat(c["id"])
            if is_open:
                st.session_state.chat_id = None
                st.session_state.messages = []
            st.rerun()

    st.divider()
    with st.expander("Settings"):
        provider = st.selectbox("Provider", list(PROVIDERS.keys()), index=0)
        base_url, key_env, models = PROVIDERS[provider]

        # Server pe key hai toh use chhupa ke rakhte hain, user ko dikhate nahi
        server_key = secret(key_env)
        if server_key:
            api_key = server_key
            st.caption("✅ API key set hai")
        else:
            api_key = st.text_input(f"API Key ({key_env})", type="password")

        model = st.selectbox("Model", models, index=0)
        custom_model = st.text_input(
            "Ya apna model naam likh (optional)",
            help="Agar upar wala model band ho gaya ho toh yahan naya naam daal.",
        ).strip()
        if custom_model:
            model = custom_model

        temperature = st.slider("Temperature (mazaa)", 0.3, 1.2, 0.7, 0.05)

    if st.button("Logout", use_container_width=True):
        try:
            get_sb().auth.sign_out()
        except Exception:
            pass
        st.session_state.clear()
        st.rerun()

# ---------- History ----------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            suno_button(msg["content"])

if not api_key:
    st.warning(f"Sidebar > Settings mein API key daal pehle bhai (ya secrets mein {key_env} daal).")
    st.stop()

client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)


def stream_reply(messages):
    """Tokens yield karta hai taaki jawab dheere-dheere likhta dikhe."""
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# ---------- Chat ----------
if raw_prompt := st.chat_input("Satyam se baat kar..."):
    prompt = raw_prompt.strip()[:MAX_PROMPT_CHARS]

    if not prompt:
        st.warning("Khaali message nahi bhej sakte bhai 😄")
    elif not check_rate_limit():
        st.error("Thoda aaram se! Bahut jaldi-jaldi messages aa rahe hain, thodi der ruk ke bhej.")
    else:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        to_send = [{"role": "system", "content": SATYAM_SYSTEM_PROMPT}] + [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-MAX_HISTORY:]
        ]

        with st.chat_message("assistant"):
            try:
                reply = st.write_stream(stream_reply(to_send))
                st.session_state.messages.append({"role": "assistant", "content": reply})
                suno_button(reply)

                # jawab aa gaya, ab database mein save karo
                try:
                    is_new = st.session_state.chat_id is None
                    if is_new:
                        st.session_state.chat_id = create_chat(prompt)
                    save_messages(
                        st.session_state.chat_id,
                        [("user", prompt), ("assistant", reply)],
                    )
                    if is_new:
                        st.rerun()  # sidebar mein nayi chat dikhane ke liye
                except Exception as e:
                    st.warning(f"Chat save nahi ho payi: {e}")

            except APIConnectionError:
                st.error("Net nahi chal raha bhai 😅 Connection check kar, phir dobara bhej.")
                st.session_state.messages.pop()
            except APITimeoutError:
                st.error("Server ne bahut der laga di. Thodi der baad try kar.")
                st.session_state.messages.pop()
            except AuthenticationError:
                st.error("API key galat hai ya expire ho gayi. Nayi key bana ke daal.")
                st.session_state.messages.pop()
            except NotFoundError:
                st.error(f"Model `{model}` nahi mila. Settings mein koi aur model chun ya naam check kar.")
                st.session_state.messages.pop()
            except RateLimitError:
                st.error("API provider ki limit khatam ho gayi. Thodi der ruk ke try kar.")
                st.session_state.messages.pop()
            except Exception as e:
                st.error(f"Kuch gadbad ho gayi: {e}")
                st.session_state.messages.pop()
        
