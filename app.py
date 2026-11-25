"""
Samenvatter - maakt samenvattingen van foto's en PDF's met Claude.

Starten op je computer:   streamlit run app.py
"""

import base64
import io

import anthropic
import streamlit as st
from PIL import Image, ImageOps

# iPhone-foto's (HEIC) kunnen openen, als pillow-heif geinstalleerd is
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

MODEL = "claude-sonnet-5-5"
MAX_IMAGE_SIDE = 1568          # grotere foto's worden verkleind (sneller en goedkoper)
MAX_TOTAL_MB = 30              # veiligheidsgrens voor alle bestanden samen

st.set_page_config(page_title="Samenvatter", page_icon="📚", layout="centered")


# ---------------------------------------------------------------------------
# 1. Wachtwoord, zodat niet iedereen jouw API-tegoed kan gebruiken
# ---------------------------------------------------------------------------
def check_password() -> bool:
    if st.session_state.get("ingelogd"):
        return True
    st.title("📚 Samenvatter")
    wachtwoord = st.text_input("Wachtwoord", type="password")
    if st.button("Inloggen"):
        if wachtwoord == st.secrets["APP_PASSWORD"]:
            st.session_state["ingelogd"] = True
            st.rerun()
        else:
            st.error("Verkeerd wachtwoord.")
    return False


if not check_password():
    st.stop()


# ---------------------------------------------------------------------------
# 2. Bestanden omzetten naar iets wat Claude kan lezen
# ---------------------------------------------------------------------------
def image_to_block(data: bytes) -> dict:
    """Foto openen, rechtzetten, verkleinen en als JPEG doorgeven."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)          # foto's van de gsm juist draaien
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buffer.getvalue()).decode(),
        },
    }


def pdf_to_block(data: bytes) -> dict:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode(),
        },
    }


# ---------------------------------------------------------------------------
# 3. De opdracht voor Claude
# ---------------------------------------------------------------------------
def build_prompt(niveau: str, taal: str, lengte: str, begrippen: bool, vragen: bool) -> str:
    if taal == "Engels":
        taal_regel = "Schrijf de volledige samenvatting in het Engels (ook titels en begrippen)."
    elif taal == "Nederlands":
        taal_regel = "Schrijf de volledige samenvatting in het Nederlands (Vlaams taalgebruik is prima)."
    else:
        taal_regel = "Schrijf de samenvatting in dezelfde taal als de leerstof."

    extra = []
    if begrippen:
        extra.append("- Sluit af met een lijst 'Kernbegrippen' met een korte uitleg per begrip.")
    if vragen:
        extra.append("- Voeg op het einde 5 oefenvragen toe, met de antwoorden apart eronder.")
    extra_tekst = "\n".join(extra)

    return f"""Je helpt een leerling ({niveau}) met studeren.
Hierboven staan pagina's uit haar cursus of handboek (foto's en/of PDF's).

Maak een duidelijke samenvatting. {taal_regel}
- Lengte: {lengte}.
- Gebruik tussentitels die de structuur van de leerstof volgen.
- Zet belangrijke begrippen, namen, jaartallen en formules in het **vet**.
- Gebruik opsommingstekens waar dat helder is, maar schrijf geen losse woorden zonder verband.
- Neem alleen op wat echt in de pagina's staat; verzin niets.
- Is een stuk onleesbaar, zeg dat dan kort.
{extra_tekst}"""


# ---------------------------------------------------------------------------
# 4. Het scherm
# ---------------------------------------------------------------------------
st.title("📚 Samenvatter")
st.write("Laad foto's of PDF's van je leerstof in en krijg een samenvatting.")

with st.sidebar:
    st.header("Instellingen")
    niveau = st.selectbox(
        "Niveau",
        ["5e jaar middelbaar", "6e jaar middelbaar", "hoger onderwijs (bachelor)", "hoger onderwijs (master)"],
    )
    taal = st.radio(
        "Taal van de samenvatting",
        ["Nederlands", "Engels", "Zelfde taal als de leerstof"],
    )
    lengte = st.radio(
        "Lengte",
        ["kort (enkel de kern)", "normaal", "uitgebreid (zo volledig mogelijk)"],
        index=1,
    )
    begrippen = st.checkbox("Lijst met kernbegrippen", value=True)
    vragen = st.checkbox("Oefenvragen toevoegen", value=False)

bestanden = st.file_uploader(
    "Foto's of PDF's (je kunt er meerdere tegelijk kiezen)",
    type=["pdf", "jpg", "jpeg", "png", "webp", "heic"],
    accept_multiple_files=True,
)

if bestanden:
    totaal_mb = sum(b.size for b in bestanden) / 1_000_000
    st.caption(f"{len(bestanden)} bestand(en), samen {totaal_mb:.1f} MB")

if st.button("✨ Maak samenvatting", type="primary", disabled=not bestanden):
    content = []
    for bestand in bestanden:
        data = bestand.getvalue()
        try:
            if bestand.name.lower().endswith(".pdf"):
                content.append(pdf_to_block(data))
            else:
                content.append(image_to_block(data))
        except Exception:
            st.error(f"Kon '{bestand.name}' niet openen. Probeer het als JPG of PDF.")
            st.stop()

    grootte_mb = sum(len(b["source"]["data"]) for b in content) / 1_000_000
    if grootte_mb > MAX_TOTAL_MB:
        st.error("Te veel of te grote bestanden in één keer. Probeer minder pagina's tegelijk.")
        st.stop()

    content.append({"type": "text", "text": build_prompt(niveau, taal, lengte, begrippen, vragen)})

    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    try:
        with st.spinner("Bezig met lezen..."):
            with client.messages.stream(
                model=MODEL,
                max_tokens=8000,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                samenvatting = st.write_stream(stream.text_stream)
        st.session_state["samenvatting"] = samenvatting
    except anthropic.APIError as fout:
        st.error(f"Er ging iets mis bij Claude: {fout}")

elif "samenvatting" in st.session_state:
    st.markdown(st.session_state["samenvatting"])

if "samenvatting" in st.session_state:
    st.download_button(
        "⬇️ Download samenvatting",
        data=st.session_state["samenvatting"],
        file_name="samenvatting.md",
        mime="text/markdown",
    )
