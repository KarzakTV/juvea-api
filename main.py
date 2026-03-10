from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import requests
import datetime
import resend
import json
import re
import os
import traceback

from shopify_webhook import webhook_router

app = FastAPI()

# --- CONFIGURATION (Via Variables d'Environnement Render) ---
URL_WEBHOOK_SHEETS = "https://script.google.com/macros/s/AKfycby9C2klTvdcW20a9B456pEPeAOvjJykR6a2DSIPA7K2qPjWzE_283-w3Mh7yBA87J8H/exec"

# On récupère les clés proprement. Si elles ne sont pas dans Render, elles vaudront None.
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

resend.api_key = RESEND_API_KEY

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=False,
    allow_methods=["*"], 
    allow_headers=["*"],
    expose_headers=["*"]
)

# --- MODELES DE DONNEES ---
class Scores(BaseModel):
    purete: int; temps: int; eclat: int; apaisement: int

class Environnement(BaseModel):
    temperature: Optional[int] = None
    humidite: Optional[int] = None
    uv: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class RequeteClient(BaseModel):
    prenom: str = "Client"
    nom: str = "Juvea"
    age: int = 30
    email: str = "client@juvea.com"
    accepts_marketing: bool = False
    attentes: List[str] = []
    exclusions: List[str] = []
    scores: Scores
    environnement: Optional[Environnement] = None
    ia_raw_scores: Optional[dict] = None 

class SosRequete(BaseModel):
    message: str
    baumann_code: str
    baumann_profil: str
    environnement: str

class InciRequete(BaseModel):
    image_b64: str
    baumann_code: str
    baumann_profil: str

# --- WEBHOOK SHOPIFY ---
app.include_router(webhook_router, prefix="/api/webhooks/shopify")

BIBLE_JUVEA = """
PHILOSOPHIE JUVEA PARIS : Nous sommes une marque de dermo-cosmétique française de luxe.
NOTRE SECRET DE FORMULATION : Nous remplaçons l'eau inactive par du Pur Jus d'Aloe Vera certifié bio.
NOS ACTIFS PHARES : Bidens Pilosa, Lactobacillus Ferment, Acide Glycolique & Salicylique.
TON : Empathique, luxueux, clinique, sur-mesure.
"""

CATALOGUE = {
    "purete": {
        "nettoyant": {"texte": "Eau Micellaire Botanique Purifiante à l'extrait de Camomille", "id": 111111111111, "image": "", "safe_grossesse": True},
        "lotion": {"texte": "Lotion Exfoliante à l'Acide Glycolique & Canneberge Bio", "id": 222222222222, "image": "", "safe_grossesse": False},
        "serum": {"texte": "Sérum Purifiant Intense Anti-Imperfections (Acide Salicylique & Arbre à Thé)", "id": 333333333333, "image": "", "safe_grossesse": False},
        "creme": {"texte": "Gel Hydratant Équilibrant sans huile au Zinc PCA", "id": 444444444444, "image": "", "safe_grossesse": True},
        "spf": {"texte": "Bouclier Solaire Minéral SPF50", "id": 555555555555, "image": "", "safe_grossesse": True},
        "actifs": ["Acide Salicylique", "Zinc PCA", "Acide Glycolique", "Huile d'Arbre à Thé"]
    },
    "temps": {
        "nettoyant": {"texte": "Lait Nettoyant Douceur Botanique (Karité & Argan)", "id": 666666666666, "image": "", "safe_grossesse": True},
        "lotion": {"texte": "Essence Repulpante Acide Hyaluronique & Thé Blanc", "id": 777777777777, "image": "", "safe_grossesse": True},
        "serum": {"texte": "Sérum Botanique Phyto-Rétinol (Bidens Pilosa & Jojoba)", "id": 888888888888, "image": "", "safe_grossesse": True},
        "yeux": {"texte": "Élixir Contour des Yeux Phyto-Rétinol & Marron d'Inde", "id": 999999999999, "image": "", "safe_grossesse": True},
        "creme": {"texte": "Crème de Jour Restructurante Anti-Âge à la Sève de Bouleau", "id": 101010101010, "image": "", "safe_grossesse": True},
        "spf": {"texte": "Bouclier Solaire Minéral SPF50", "id": 555555555555, "image": "", "safe_grossesse": True},
        "actifs": ["Phyto-Rétinol (Bidens Pilosa)", "Acide Hyaluronique", "Sève de Bouleau", "Escine"]
    },
    "eclat": {
        "nettoyant": {"texte": "Gel Nettoyant Éclat aux Baies Nordiques", "id": 121212121212, "image": "", "safe_grossesse": True},
        "lotion": {"texte": "Concentré Peeling Doux AHA & Thé Blanc", "id": 131313131313, "image": "", "safe_grossesse": False},
        "serum": {"texte": "Sérum Perfecteur de Pigment à l'Alpha-Arbutine", "id": 141414141414, "image": "", "safe_grossesse": False},
        "creme": {"texte": "Gel Booster Antioxydant au Ginkgo Biloba", "id": 151515151515, "image": "", "safe_grossesse": True},
        "spf": {"texte": "Bouclier Solaire Minéral Teinté SPF50", "id": 555555555555, "image": "", "safe_grossesse": True},
        "actifs": ["Alpha-Arbutine", "Acides de Fruits (AHA)", "Ginkgo Biloba", "Vitamine C"]
    },
    "apaisement": {
        "nettoyant": {"texte": "Démaquillant Biphasé Haute Tolérance à l'Argousier", "id": 161616161616, "image": "", "safe_grossesse": True},
        "serum": {"texte": "Sérum Gélifié aux Prébiotiques Bioactifs (Lactobacillus)", "id": 171717171717, "image": "", "safe_grossesse": True},
        "huile": {"texte": "Huile de Soin Nourrissante aux Omégas (Jojoba & Argousier)", "id": 181818181818, "image": "", "safe_grossesse": True},
        "creme": {"texte": "Baume de Nuit Réparateur aux Céramides & Cacao", "id": 191919191919, "image": "", "safe_grossesse": True},
        "spf": {"texte": "Bouclier Solaire Minéral SPF50", "id": 555555555555, "image": "", "safe_grossesse": True},
        "actifs": ["Céramides Végétaux", "Prébiotiques (Lactobacillus)", "Huile d'Argousier", "Jus d'Aloe Vera"]
    }
}

SERUM_UNIVERSEL = {"texte": "Sérum Universel Hydratation Profonde (Acide Hyaluronique Pur)", "id": 999999888888, "image": "", "safe_grossesse": True}

def calculer_baumann(scores: Scores):
    b_od = "O" if scores.purete > 7 else "D"   
    b_sr = "S" if scores.apaisement > 7 else "R" 
    b_pn = "P" if scores.eclat > 6 else "N"    
    b_wt = "W" if scores.temps > 6 else "T"    
    code = f"{b_od}{b_sr}{b_pn}{b_wt}"
    
    txt_od = "Une production de sébum importante (Grasse)" if b_od == "O" else "Un déficit en lipides naturels (Sèche)"
    txt_sr = "Une barrière cutanée réactive aux agressions (Sensible)" if b_sr == "S" else "Une barrière protectrice robuste (Résistante)"
    txt_pn = "Une tendance aux taches et hyperpigmentation (Pigmentée)" if b_pn == "P" else "Un teint globalement uniforme (Non-Pigmentée)"
    txt_wt = "Une prédisposition au vieillissement structurel (Rides)" if b_wt == "W" else "Une bonne élasticité structurelle (Lisse)"
    
    a_fuir = []
    if b_od == "O": a_fuir.append("Huiles comédogènes pures, cires lourdes occlusives")
    if b_od == "D": a_fuir.append("Nettoyants moussants aux sulfates, alcool dénaturé")
    if b_sr == "S": a_fuir.append("Gommages mécaniques à grains durs, parfums synthétiques forts")
    if b_pn == "P": a_fuir.append("Exposition solaire sans protection SPF50 minérale")
    
    return {
        "code": code,
        "profil": f"Peau {txt_od.split('(')[1][:-1]}, {txt_sr.split('(')[1][:-1]}, {txt_pn.split('(')[1][:-1]} et {txt_wt.split('(')[1][:-1]}.",
        "explication": f"Votre typologie de Baumann indique que votre peau est caractérisée par : {txt_od.lower()}, {txt_sr.lower()}, {txt_pn.lower()} et {txt_wt.lower()}.",
        "avantages": "Des textures fluides, Acide Salicylique" if b_od == "O" else "Des céramides, Acide Hyaluronique, Huiles d'Omégas",
        "a_fuir": ", ".join(a_fuir)
    }

def determiner_climat_par_ip(ip: str):
    mois = datetime.datetime.now().month
    if ip == "127.0.0.1" or ip.startswith("192.168."): return "Climat tempéré standard"
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,lat", timeout=3).json()
        if res.get("status") == "success":
            lat = res.get("lat", 0)
            if lat >= 0: saison = "Hiver" if mois in [12, 1, 2] else "Été" if mois in [6, 7, 8] else "Mi-saison"
            else: saison = "Été" if mois in [12, 1, 2] else "Hiver" if mois in [6, 7, 8] else "Mi-saison"
            return f"{res.get('city', '')}, {res.get('country', '')} ({saison})"
    except: pass
    return "Climat tempéré standard"

def formater_donnees_environnementales(env: Environnement, client_ip: str):
    if env and env.temperature is not None:
        return f"{env.temperature}°C, {env.humidite}% d'humidité, Indice UV {env.uv}"
    return determiner_climat_par_ip(client_ip)

def generer_analyse_claude(prenom, age, profil, profil_secondaire, attentes, contexte, baumann_code, bible, scores_dict, ia_raw_scores):
    
    photo_context = ""
    if ia_raw_scores:
        photo_context = (
            f"La note IA de la caméra biométrique indique (sur 100) : Rides {ia_raw_scores.get('rides', 'N/A')}, Taches {ia_raw_scores.get('taches', 'N/A')}, "
            f"Rougeurs {ia_raw_scores.get('rougeurs', 'N/A')}, Pores {ia_raw_scores.get('pores', 'N/A')}. Tu dois les mentionner pour prouver l'analyse."
        )

    prompt_system = f"""Tu es l'IA Experte en Dermo-Cosmétique de Juvea Paris.
RÈGLE ABSOLUE 1 : Ne propose JAMAIS de consulter un cabinet physique Juvea. Ne propose un médecin que si la situation est grave.
RÈGLE ABSOLUE 2 : Ton ton est LUXUEUX, RASSURANT et HAUTEMENT CLINIQUE. Tu dois fournir une expertise riche, ultra-détaillée et personnalisée. Prends tout l'espace nécessaire pour développer tes arguments scientifiques.
BASE DE CONNAISSANCES :
{bible}
STRUCTURE JSON EXACTE REQUISE :
{{
  "analyse_pro": "3 ou 4 paragraphes élégants, détaillés et cliniques liant l'âge ({age} ans), le climat ({contexte}) et les problèmes ({profil}, {profil_secondaire}) à la typologie {baumann_code}. {photo_context}",
  "focus_actif": "1 paragraphe complet et très approfondi expliquant l'action biologique de nos actifs recommandés.",
  "conseils_vie": "1 paragraphe détaillé sur l'hygiène de vie globale et l'impact de la météo actuelle.",
  "exclusions_texte": "1 paragraphe précis proscrivant les ingrédients irritants avec les raisons scientifiques.",
  "decryptage_inci": "1 explication développée sur le fait que le Pur Jus d'Aloe Vera remplace l'eau chez Juvea pour une efficacité maximale."
}}
IMPORTANT : Renvoie UNIQUEMENT un objet JSON valide."""
    
    prompt_user = f"Patiente: {prenom}, {age} ans. Typologie: {baumann_code}. Environnement: {contexte}. Rédige l'expertise complète et fluide."
    
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    
    payload = {
        "model": "claude-3-5-sonnet-20241022", # Modèle puissant pour Render
        "max_tokens": 2500, 
        "temperature": 0.4, 
        "system": prompt_system, 
        "messages": [
            {"role": "user", "content": prompt_user}
        ]
    }
    
    fallback = {
        "analyse_pro": f"Vos marqueurs liés à votre âge ({age} ans) et votre environnement ({contexte}) indiquent que votre film protecteur est fragilisé, ce qui accentue {profil} et {profil_secondaire}. Votre typologie {baumann_code} le confirme. Nous consolidons les fondations de votre épiderme.",
        "focus_actif": "Nos alternatives végétales hautement dosées agissent comme des messagers cellulaires.",
        "conseils_vie": f"Protégez-vous des agressions climatiques ({contexte}) et régulez votre sommeil.",
        "exclusions_texte": "Cessez l'utilisation de tensioactifs agressifs qui décapent la peau.",
        "decryptage_inci": "L'eau est inactive. Le Jus d'Aloe Vera bio de nos formules offre une hydratation cellulaire active."
    }
    
    try:
        if not ANTHROPIC_API_KEY:
            print("❌ ERREUR : La clé ANTHROPIC_API_KEY n'est pas configurée dans Render.", flush=True)
            return fallback
            
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            raw_text = r.json()["content"][0]["text"]
            clean_text = raw_text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{[\s\S]*\}', clean_text)
            if match: 
                try:
                    return json.loads(match.group(0))
                except Exception: pass
        else:
            print(f"❌ Erreur API Claude: {r.status_code} - {r.text}", flush=True)
    except Exception as e:
        print(f"❌ Exception API Claude: {e}", flush=True)
    
    return fallback

def envoyer_email_resend(client: RequeteClient, baumann_code: str, analyse_pro: str):
    if not RESEND_API_KEY: return
    html_content = f"""<div style="font-family: Arial, sans-serif; color: #1f1f1f; max-width: 600px; margin: auto; padding: 40px 20px; background-color: #ffffff;"><div style="text-align: center; margin-bottom: 40px;"><h1 style="color: #6E7B74; font-size: 28px; letter-spacing: 2px; text-transform: uppercase; margin: 0;">Juvea Paris</h1></div><h2 style="text-align: center; font-weight: 400; font-size: 22px; margin-bottom: 30px;">Le Carnet d'Expertise de {client.prenom}</h2><div style="background: #F5F0EA; padding: 25px; text-align: center; margin-bottom: 30px; border-left: 4px solid #6E7B74;"><p style="font-size: 12px; color: #6E7B74; text-transform: uppercase; margin: 0 0 10px 0;">Typologie Baumann</p><strong style="font-size: 24px;">{baumann_code}</strong></div><p style="line-height: 1.8; font-size: 14px;">{analyse_pro.replace(chr(10), '<br><br>')}</p></div>"""
    try: resend.Emails.send({"from": "Juvea Paris <onboarding@resend.dev>", "to": [client.email], "subject": f"Votre Résultat ({baumann_code})", "html": html_content})
    except: pass

def synchroniser_externe(client: RequeteClient, analyse_pro: str, baumann_code: str):
    envoyer_email_resend(client, baumann_code, analyse_pro)
    try: requests.post(URL_WEBHOOK_SHEETS, json={"date": datetime.datetime.now().strftime("%Y-%m-%d"), "prenom": client.prenom, "email": client.email, "analyse": f"[{baumann_code}] {analyse_pro[:150]}"}, timeout=10)
    except: pass
    
    if not SHOPIFY_TOKEN: return
    
    try:
        h = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
        res = requests.get(f"https://juvea-3.myshopify.com/admin/api/2024-01/customers/search.json?query=email:{client.email}", headers=h, timeout=10).json()
        d = {"first_name": client.prenom, "last_name": client.nom, "note": f"Type: {baumann_code}.", "tags": f"Diagnostic-Juvea, Baumann-{baumann_code}", "email_marketing_consent": {"state": "subscribed" if client.accepts_marketing else "not_subscribed"}}
        if res.get("customers") and len(res["customers"]) > 0: requests.put(f"https://juvea-3.myshopify.com/admin/api/2024-01/customers/{res['customers'][0]['id']}.json", json={"customer": d}, headers=h, timeout=10)
        else: d["email"] = client.email; requests.post("https://juvea-3.myshopify.com/admin/api/2024-01/customers.json", json={"customer": d}, headers=h, timeout=10)
    except: pass

def generer_rituel_juvea(scores: Scores, attentes: List[str], exclusions: List[str], prenom: str, age: int, client_ip: str, environnement: Environnement, ia_raw_scores: dict):
    baumann_data = calculer_baumann(scores)
    s_dict = {"purete": scores.purete, "temps": scores.temps, "eclat": scores.eclat, "apaisement": scores.apaisement}
    tries = sorted(s_dict.items(), key=lambda i: i[1], reverse=True)
    p1 = tries[0][0]; p2 = tries[1][0] 
    noms = {"purete": "la pureté", "temps": "les signes de l'âge", "eclat": "l'éclat", "apaisement": "l'apaisement"}
    
    cb = CATALOGUE.get(p1, CATALOGUE["apaisement"])
    cs = CATALOGUE.get(p2, CATALOGUE["apaisement"])
    est_enceinte = "grossesse" in exclusions
    def valide(p): return False if not p else (False if est_enceinte and not p.get("safe_grossesse", True) else True)

    ess = []; comp = []
    if valide(cb.get("nettoyant")): ess.append(cb["nettoyant"]); comp.append(cb["nettoyant"])
    if valide(cb.get("lotion")): comp.append(cb["lotion"])
    serum = cs.get("serum") if valide(cs.get("serum")) else SERUM_UNIVERSEL
    comp.append(serum)
    if valide(cb.get("yeux")): comp.append(cb["yeux"])
    if valide(cb.get("huile")): comp.append(cb["huile"])
    if valide(cb.get("creme")): ess.append(cb["creme"]); comp.append(cb["creme"])
    if valide(cb.get("spf")): ess.append(cb["spf"]); comp.append(cb["spf"])
        
    ctx = formater_donnees_environnementales(environnement, client_ip)
    txt_ia = generer_analyse_claude(prenom, age, noms.get(p1, p1), noms.get(p2, p2), ", ".join(attentes), ctx, baumann_data["code"], BIBLE_JUVEA, s_dict, ia_raw_scores)
    actifs = list(set(cb.get("actifs", []) + cs.get("actifs", [])))
    return txt_ia, ess, comp, actifs, baumann_data

@app.post("/api/diagnostic")
async def diagnostic(client: RequeteClient, request: Request, background_tasks: BackgroundTasks):
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
        
        txt_ia, ess, comp, actifs, baumann_data = generer_rituel_juvea(client.scores, client.attentes, client.exclusions, client.prenom, client.age, client_ip, client.environnement, client.ia_raw_scores)
        
        res = {
            "client": f"{client.prenom} {client.nom}",
            "baumann_code": baumann_data["code"], "baumann_profil": baumann_data["profil"], "baumann_explication": baumann_data["explication"], "baumann_avantages": baumann_data["avantages"], "baumann_a_fuir": baumann_data["a_fuir"],
            "analyse_pro": txt_ia.get("analyse_pro", ""), "focus_actif": txt_ia.get("focus_actif", ""), "conseils_vie": txt_ia.get("conseils_vie", ""), "exclusions_texte": txt_ia.get("exclusions_texte", ""), "decryptage_inci": txt_ia.get("decryptage_inci", ""),
            "offre_essentielle": ess, "offre_complete": comp, "actifs_recommandes": actifs,
            "ia_raw_scores": client.ia_raw_scores
        }
        background_tasks.add_task(synchroniser_externe, client, txt_ia.get("analyse_pro", ""), baumann_data["code"])
        return res
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

@app.post("/api/sos-peau")
async def sos_peau_chat(req: SosRequete):
    if not ANTHROPIC_API_KEY:
        return {"reponse": "Clé API Anthropic manquante sur le serveur."}
        
    prompt_system = f"Tu es l'Expert Dermo-Cosmétique d'Urgence Juvea Paris. Patient Baumann : {req.baumann_code}. Météo : {req.environnement}. Concis, rassurant, luxueux."
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 500, "temperature": 0.5, "system": prompt_system, "messages": [{"role": "user", "content": req.message}]}
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            return {"reponse": r.json()["content"][0]["text"]}
        else:
            # On imprime dans les logs pour la traçabilité
            print(f"❌ Erreur API SOS Peau: {r.status_code} - {r.text}", flush=True)
            # MODIFICATION : On renvoie l'erreur détaillée directement à l'application pour voir le problème en direct
            return {"reponse": f"ERREUR CLAUDE : Code {r.status_code} - {r.text}"}
    except Exception as e:
        print(f"❌ Exception API SOS Peau: {e}", flush=True)
        return {"reponse": f"ERREUR SERVEUR : {str(e)}"}

@app.post("/api/scan-inci")
async def scan_inci_vision(req: InciRequete):
    if not ANTHROPIC_API_KEY:
        return {"error": "Clé API Anthropic manquante.", "statut": "erreur", "analyse": "Clé API manquante sur le serveur."}
        
    cat_str = json.dumps(CATALOGUE, ensure_ascii=False)
    prompt_system = f"Analyse l'image INCI pour le type {req.baumann_code}. Recommande via : {cat_str}. JSON uniquement."
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    b64_clean = req.image_b64.split(",")[-1] if "," in req.image_b64 else req.image_b64
    payload = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 800, "system": prompt_system, "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_clean}}, {"type": "text", "text": "Analyse INCI."}]}]}
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            return json.loads(r.json()["content"][0]["text"])
        else:
            print(f"❌ Erreur API Scan INCI: {r.status_code} - {r.text}", flush=True)
            return {"error": "Analyse impossible.", "statut": "erreur", "analyse": f"ERREUR CLAUDE : Code {r.status_code} - {r.text}"}
    except Exception as e:
        print(f"❌ Exception API Scan INCI: {e}", flush=True)
        return {"error": "Analyse impossible.", "statut": "erreur", "analyse": f"ERREUR SERVEUR : {str(e)}"}