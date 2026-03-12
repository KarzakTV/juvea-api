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

# --- NOUVEAUX IMPORTS POUR LES NOTIFICATIONS ---
import firebase_admin
from firebase_admin import credentials, messaging, firestore
from apscheduler.schedulers.background import BackgroundScheduler

from shopify_webhook import webhook_router

app = FastAPI()

# --- CONFIGURATION (Via Variables d'Environnement Render) ---
URL_WEBHOOK_SHEETS = "https://script.google.com/macros/s/AKfycby9C2klTvdcW20a9B456pEPeAOvjJykR6a2DSIPA7K2qPjWzE_283-w3Mh7yBA87J8H/exec"

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

# --- INITIALISATION FIREBASE ADMIN ---
CHEMIN_SECRET = "/etc/secrets/firebase-key.json"

if os.path.exists(CHEMIN_SECRET):
    if not firebase_admin._apps:
        cred = credentials.Certificate(CHEMIN_SECRET)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase Admin initialisé avec succès.")
else:
    db = None
    print("⚠️ Fichier secret Firebase introuvable. Mode développement (sans push).")

# --- FONCTIONS DE NOTIFICATIONS PUSH (HORLOGE) ---
def push_routine_quotidienne(moment):
    """Envoie un rappel le matin (8h) ou le soir (20h)"""
    if not db: return
    try:
        users_ref = db.collection('users').stream()
        for doc in users_ref:
            user = doc.to_dict()
            token = user.get('fcmToken')
            if token:
                prenom = user.get('prenom', 'Beauté')
                if moment == "matin":
                    titre = f"☀️ Bonjour {prenom}"
                    corps = "Il est temps pour votre rituel d'hydratation matinal."
                else:
                    titre = f"🌙 Douce nuit {prenom}"
                    corps = "Prenez un moment pour votre rituel du soir avant de dormir."
                
                msg = messaging.Message(
                    notification=messaging.Notification(title=titre, body=corps),
                    token=token
                )
                try: messaging.send(msg)
                except Exception: pass # Ignore si le jeton du client a expiré
    except Exception as e:
        print("Erreur Push Quotidien :", e)

def push_cycle_28_jours():
    """Vérifie si la dernière expertise date de 28 jours exactement"""
    if not db: return
    try:
        users_ref = db.collection('users').stream()
        aujourd_hui = datetime.datetime.now(datetime.timezone.utc)
        
        for doc in users_ref:
            user = doc.to_dict()
            token = user.get('fcmToken')
            last_scan = user.get('lastScanDate')
            
            if token and last_scan:
                try:
                    date_scan = datetime.datetime.fromisoformat(last_scan.replace('Z', '+00:00'))
                    delta = aujourd_hui - date_scan
                    if delta.days == 28:
                        msg = messaging.Message(
                            notification=messaging.Notification(
                                title="⏳ Cycle cutané terminé",
                                body=f"{user.get('prenom', '')}, votre peau s'est renouvelée. Mettez à jour votre expertise !"
                            ),
                            token=token
                        )
                        messaging.send(msg)
                except Exception:
                    pass
    except Exception as e:
        print("Erreur Push 28 Jours :", e)

def push_alerte_exposome():
    """Vérifie la pollution locale du client et envoie une alerte"""
    if not db: return
    try:
        users_ref = db.collection('users').stream()
        for doc in users_ref:
            user = doc.to_dict()
            token = user.get('fcmToken')
            lat = user.get('latitude')
            lon = user.get('longitude')
            
            if token and lat and lon:
                url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm2_5"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    pm25 = data.get('current', {}).get('pm2_5', 0)
                    
                    if pm25 > 25:
                        msg = messaging.Message(
                            notification=messaging.Notification(
                                title="⚠️ Alerte Qualité de l'Air",
                                body="L'air est pollué chez vous aujourd'hui. Un double nettoyage s'impose ce soir."
                            ),
                            token=token
                        )
                        try: messaging.send(msg)
                        except Exception: pass
    except Exception as e:
        print("Erreur Push Météo :", e)

# --- DÉMARRAGE DE L'HORLOGE AU LANCEMENT DE L'API ---
@app.on_event("startup")
def start_scheduler():
    scheduler = BackgroundScheduler()
    # Rappel Matin (tous les jours à 08h00 UTC)
    scheduler.add_job(push_routine_quotidienne, 'cron', hour=8, minute=0, args=["matin"])
    # Rappel Soir (tous les jours à 20h00 UTC)
    scheduler.add_job(push_routine_quotidienne, 'cron', hour=20, minute=0, args=["soir"])
    # Rappel 28 jours (tous les jours à 12h00 UTC)
    scheduler.add_job(push_cycle_28_jours, 'cron', hour=12, minute=0)
    # Alerte Météo/Pollution (tous les jours à 09h00 UTC)
    scheduler.add_job(push_alerte_exposome, 'cron', hour=9, minute=0)
    
    scheduler.start()
    print("⏰ Planificateur de notifications démarré avec succès !")

# --- ENDPOINT DE TEST POUR LES NOTIFICATIONS PUSH ---
@app.get("/api/test-push")
def test_push_notification(email: Optional[str] = None):
    """Permet de déclencher une notification immédiatement pour tester l'APK."""
    if not db:
        return {"status": "erreur", "message": "Firebase n'est pas initialisé. Vérifiez votre Secret File sur Render."}
    try:
        if email:
            users_ref = db.collection('users').where('email', '==', email).stream()
        else:
            users_ref = db.collection('users').limit(10).stream() # Envoie à max 10 appareils pour éviter le spam
            
        count = 0
        for doc in users_ref:
            user = doc.to_dict()
            token = user.get('fcmToken')
            if token:
                msg = messaging.Message(
                    notification=messaging.Notification(
                        title="✨ Test Juvea Paris",
                        body=f"Bonjour {user.get('prenom', '')}, vos notifications push natives fonctionnent !"
                    ),
                    token=token
                )
                try:
                    messaging.send(msg)
                    count += 1
                except Exception as e:
                    print(f"Erreur d'envoi pour le token {token[:10]}... : {str(e)}")
        
        return {"status": "succès", "message": f"Notification de test envoyée à {count} appareil(s)."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "erreur", "message": str(e)}

# --- POURCENTAGES BAUMANN (Répartition réaliste) ---
BAUMANN_PCT = {
    "ORPT": 8.5, "ORPW": 12.2, "ORNT": 7.1, "ORNW": 9.4,
    "OSPT": 6.3, "OSPW": 11.5, "OSNT": 5.8, "OSNW": 8.7,
    "DRPT": 4.2, "DRPW": 6.8,  "DRNT": 3.9, "DRNW": 5.1,
    "DSPT": 2.4, "DSPW": 4.5,  "DSNT": 1.8, "DSNW": 1.8
}

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
    prenom: str = "Client"
    image_b64: Optional[str] = None

class InciRequete(BaseModel):
    image_b64: str
    baumann_code: str
    baumann_profil: str

# --- WEBHOOK SHOPIFY ---
app.include_router(webhook_router, prefix="/api/webhooks/shopify")

BIBLE_JUVEA = """
PHILOSOPHIE JUVEA PARIS : Nous sommes une marque de dermo-cosmétique française de luxe.
NOTRE SECRET DE FORMULATION : Nous remplaçons l'eau inactive par du Pur Jus d'Aloe Vera certifié bio.
TON : Chaleureux, bienveillant, fluide, accessible. Pas de jargon médical lourd.
"""

CATALOGUE = {
    "purete": {
        "nettoyant": {"texte": "Soin anti-acné", "actif_phare": "Acide Salicylique & Arbre à Thé", "id": 111111111111, "image": "", "safe_grossesse": False, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Kaolin, Argania Spinosa (Argan) Kernel Oil, Melaleuca Alternifolia (Tea Tree) Leaf Oil, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Isoamyl Laurate, Salicylic Acid, Sodium PCA, Propanediol, Potassium Hydroxide, Xanthan Gum, Polyglyceryl-6 Behenate, Parfum/Fragrance, Cellulose, Palmitic Acid, Stearic Acid, Aqua/Water, Rhodomyrtus Tomentosa (Rose Myrtle) Fruit Extract, Ribes Grossularia (Gooseberry) Fruit Extract, Vaccinium Myrtillus (Blueberry) Fruit Extract, Ascorbyl Palmitate, Tocopherol, Charcoal Powder, Limonene, Citral, Linalool, Citronellol, Geraniol"},
        "lotion": {"texte": "Lotion Tonique Exfoliante à l'Acide Glycolique", "actif_phare": "Acide Glycolique", "id": 222222222222, "image": "", "safe_grossesse": False, "inci": "Aqua, Glycolic Acid, Glycerin, Potassium Hydroxide, Betaine, Sodium PCA, Sodium Levulinate, Phenethyl Alcohol, Sodium Benzoate, Vaccinium Macrocarpon (Cranberry) Fruit Extract, Vaccinium Vitis-Idaea (Lingonberry) Fruit Extract, Alcohol"},
        "serum": {"texte": "Sérum Gel Niacinamide", "actif_phare": "Niacinamide", "id": 333333333333, "image": "", "safe_grossesse": True, "inci": "Aqua/Water, Alcohol, Niacinamide, Glycerin, Cellulose Gum, Algin, Potassium Hydroxide, Parfum/Fragrance, Sodium Phytate, Ginkgo Biloba (Ginkgo) Leaf Extract, Citric Acid, Sodium Benzoate, Potassium Sorbate"},
        "creme": {"texte": "Gel Hydratant Sans Huile", "actif_phare": "Zinc PCA", "id": 444444444444, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Pentylene Glycol, Butylene Glycol, Betaine, Sclerotium Gum, Zinc PCA, Aqua, Propanediol, Parfum, Nasturtium Officinale (Watercress) Flower/Leaf Extract, Sodium Phytate, Potassium Hydroxide, Sodium Hyaluronate, Rhamnose, Glucose, Glucuronic Acid, Limonene, Linalool, Geraniol, Citral"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "actif_phare": "Filtres Minéraux", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Acide Salicylique", "Zinc PCA", "Acide Glycolique", "Huile d'Arbre à Thé", "Niacinamide"]
    },
    "temps": {
        "nettoyant": {"texte": "Lait Nettoyant Doux", "actif_phare": "Karité & Argan", "id": 666666666666, "image": "", "safe_grossesse": True, "inci": "Aqua, Helianthus Annuus (Sunflower) Seed Oil, Sucrose Distearate, Glycerin, Dicaprylyl Carbonate, Isoamyl Laurate, Sucrose Stearate, Butyrospermum Parkii (Shea) Butter, Sodium Levulinate, Palmitic Acid, Stearic Acid, Xanthan Gum, Parfum, Sodium Anisate, Argania Spinosa (Argan) Kernel Oil, Persea Gratissima (Avocado) Oil, Simmondsia Chinensis (Jojoba) Seed Oil, Lactic Acid, Centaurea Cyanus (Cornflower) Flower Extract, Paeonia Lactiflora (Peony) Root Extract, Ascorbyl Palmitate, Sodium Phytate, Tocopherol, Linalool, Limonene, Benzyl Salicylate, Citral"},
        "lotion": {"texte": "Gel Booster Double Hydratation + AH", "actif_phare": "Acide Hyaluronique", "id": 777777777777, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Pentylene Glycol, Butylene Glycol, Glycerin, Sodium PCA, Aqua/Water, Propanediol, Cellulose Gum, Parfum/Fragrance, Algin, Camellia Sinensis (White Tea) Leaf Extract, Salvia Officinalis (Sage) Leaf Extract, Hydrolyzed Hyaluronic Acid, Lactic Acid, Sodium Hyaluronate, Sodium Phytate, Rhamnose, Glucose, Glucuronic Acid"},
        "serum": {"texte": "Crème hydratante alternative au rétinol", "actif_phare": "Phyto-Rétinol (Bidens Pilosa)", "id": 888888888888, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Simmondsia Chinensis (Jojoba) Seed Oil, Glycerin, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Aqua/Water, Sodium PCA, Dipalmitoyl Hydroxyproline, Astrocaryum Murumuru Seed Butter, Hippophae Rhamnoides (Sea Buckthorn) Fruit Extract, Gossypium Herbaceum Seed Oil, Propanediol, Bidens Pilosa Extract, Dicaprylyl Carbonate, Polyglyceryl-6 Behenate, Parfum/Fragrance, Linum Usitatissimum Seed Oil, Mangifera Indica (Mango) Seed Butter, Caprylic/Capric Triglyceride, Coco-Caprylate, Xanthan Gum, Octyldodecanol, Palmitic Acid, Stearic Acid, Tocopherol, Ascorbyl Palmitate, Potassium Hydroxide, Rhodomyrtus Tomentosa (Rose Myrtle) Fruit Extract, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Sodium Phytate, Alteromonas Ferment Extract, Phenethyl Alcohol, Geraniol, Citronellol, Pelargonium Graveolens Flower Oil, Linalool, Citral"},
        "yeux": {"texte": "Sérum contour des yeux alternatif au rétinol", "actif_phare": "Phyto-Rétinol & Marron d'Inde", "id": 999999999999, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Coconut Alkanes, Pentylene Glycol, Aqua/Water, Simmondsia Chinensis (Jojoba) Seed Oil, Sodium PCA, Polyglyceryl-6 Stearate, Glyceryl Stearate Citrate, Borago Officinalis (Borage) Seed Oil, Caprylic/Capric Triglyceride, Dipalmitoyl Hydroxyproline, Ricinus Communis (Castor) Seed Oil, Astrocaryum Murumuru Seed Butter, Gossypium Herbaceum Seed Oil, Bidens Pilosa Extract, Linum Usitatissimum Seed Oil, Parfum/Fragrance, CI 77163 (Bismuth Chloride Oxide), Polyglyceryl-6 Behenate, Rhus Verniciflua Peel Cera/Rhus Succedanea Fruit Cera, Xanthan Gum, Aesculus Hippocastanum (Horse Chestnut) Seed Extract, Cellulose, Tocopherol, Ascorbyl Palmitate, Potassium Hydroxide, Mangifera Indica (Mango) Seed Butter, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Sodium Phytate, Octyldodecanol, Alteromonas Ferment Extract, Phenethyl Alcohol, Escin, Geraniol, Citronellol, Pelargonium Graveolens Flower Oil, Linalool, Citral"},
        "creme": {"texte": "Crème de jour anti-âge", "actif_phare": "Sève de Bouleau", "id": 101010101010, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Simmondsia Chinensis (Jojoba) Seed Oil, Glycerin, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Betaine, Isoamyl Laurate, Aqua, Butyrospermum Parkii (Shea) Butter, Parfum, Caprylic/Capric Triglyceride, Polyglyceryl-6 Behenate, Cellulose, CI 77891 (Titanium Dioxide), Mica, Palmitic Acid, Stearic Acid, Vaccinium Vitis-Idaea (Lingonberry) Fruit Extract, Xanthan Gum, Echinacea Purpurea (Coneflower) Flower/Leaf/Stem Extract, Ribes Nigrum (Black Currant) Fruit Extract, Sambucus Nigra (Elder) Flower Extract, Ascorbyl Palmitate, Persea Gratissima (Avocado) Oil, Tocopherol, Hydrolyzed Hyaluronic Acid, Potassium Hydroxide, Sodium Hyaluronate, Sodium Phytate, Alteromonas Ferment Extract, Phenethyl Alcohol, Tin Oxide, Alcohol, Benzyl Salicylate, Limonene, Citral, Linalool"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "actif_phare": "Filtres Minéraux", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Phyto-Rétinol (Bidens Pilosa)", "Acide Hyaluronique", "Sève de Bouleau", "Escine"]
    },
    "eclat": {
        "nettoyant": {"texte": "Nettoyant visage éclat radieux", "actif_phare": "Baies Nordiques", "id": 121212121212, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Coco-Glucoside, Cocamidopropyl Betaine, Glycerin, Aqua/Water, Xanthan Gum, Propanediol, Rubus Fruticosus (Blackberry) Fruit Extract, Sodium PCA, Sodium Levulinate, Lactic Acid, Acacia Senegal Gum, Sodium Anisate, Acorus Calamus (Sweet Flag) Root Extract, Parfum/Fragrance, Salvia Officinalis (Sage) Leaf Extract, Rhamnose, CI 77491 (Iron Oxides), Glucose, Glucuronic Acid, Arctium Lappa (Burdock) Root Extract, Citric Acid, Sodium Benzoate, Potassium Sorbate, Linalool, Limonene"},
        "lotion": {"texte": "Concentré Peeling AHA", "actif_phare": "Acides de Fruits (AHA)", "id": 131313131313, "image": "", "safe_grossesse": False, "inci": "Aqua/Water, Lactic Acid, Pentylene Glycol, Potassium Hydroxide, Butylene Glycol, Glycerin, Sodium Hyaluronate, Camellia Sinensis (White Tea) Leaf Extract, Salvia Officinalis (Sage) Leaf Extract"},
        "serum": {"texte": "Sérum perfecteur de pigment", "actif_phare": "Alpha-Arbutine", "id": 141414141414, "image": "", "safe_grossesse": False, "inci": "Aqua, Glycerin, Caprylic/Capric Triglyceride, Helianthus Annuus (Sunflower) Seed Oil, Pentylene Glycol, Cetearyl Alcohol, Sodium PCA, Glyceryl Stearate Citrate, Alpha-Arbutin, Astrocaryum Murumuru Seed Butter, Gossypium Herbaceum Seed Oil, Bidens Pilosa Extract, Cellulose, Linum Usitatissimum Seed Oil, Parfum, Xanthan Gum, Ascorbyl Palmitate, Lactic Acid, Ascophyllum Nodosum Extract, Sodium Phytate, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Tocopherol, Limonene, Citrus Limon Peel Oil, Pogostemon Cablin Oil, Linalool, Juniperus Virginiana Oil, Cedrus Atlantica Oil/Extract, Pinene, Vanillin, Menthol, Citral, Beta-Caryophyllene"},
        "creme": {"texte": "Gel Booster au ginkgo antioxydant", "actif_phare": "Ginkgo Biloba", "id": 151515151515, "image": "", "safe_grossesse": True, "inci": "Aqua, Alcohol, Glycerin, Carrageenan, Cellulose Gum, Ceratonia Siliqua Gum, Parfum, Glucose, Ginkgo Biloba (Ginkgo) Leaf Extract, Citric Acid, Sodium Phytate, Camellia Sinensis (Green Tea) Leaf Extract, Potassium Hydroxide, Quercus Robur (Oak) Bark Extract, Vitis Vinifera (Grape) Seed Extract, Sodium Benzoate, Potassium Sorbate"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "actif_phare": "Filtres Minéraux", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Alpha-Arbutine", "Acides de Fruits (AHA)", "Ginkgo Biloba", "Vitamine C"]
    },
    "apaisement": {
        "nettoyant": {"texte": "Démaquillant BiPhasic, sans parfum", "actif_phare": "Huile d'Argousier", "id": 161616161616, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Isoamyl Laurate, Coco-Caprylate/Caprate, Butylene Glycol, Glycerin, Coconut Alkanes, Sodium Chloride, Aqua, Sodium Levulinate, Tocopherol, Sodium Benzoate, Caprylyl/Capryl Glucoside, Lactic Acid, Sodium Phytate, Chamomilla Recutita (Camomile) Flower Extract, Hippophae Rhamnoides (Sea-Buckthorn) Fruit Extract, Rubus Idaeus (Raspberry) Fruit Extract, Capsicum Annuum (Paprika) Fruit Extract, Sodium Hyaluronate, Helianthus Annuus (Sunflower) Seed Oil, Citric Acid, Potassium Sorbate, Rosmarinus Officinalis (Rosemary) Leaf Extract"},
        "serum": {"texte": "Sérum Gel aux Prébiotiques Bioactifs", "actif_phare": "Prébiotiques (Lactobacillus)", "id": 171717171717, "image": "", "safe_grossesse": True, "inci": "Aqua/Water, Alcohol, Glycerin, Sodium PCA, Cellulose Gum, Algin, Lactobacillus Ferment Lysate, Parfum/Fragrance, Sodium Phytate, Potassium Sorbate, Sodium Benzoate, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Pogostemon Cablin Oil"},
        "huile": {"texte": "Huile visage nourrissante", "actif_phare": "Omégas (Jojoba & Argousier)", "id": 181818181818, "image": "", "safe_grossesse": True, "inci": "Simmondsia Chinensis (Jojoba) Seed Oil, Decyl Cocoate, Solanum Lycopersicum (Tomato) Fruit Extract, Hippophae Rhamnoides (Sea Buckthorn) Fruit Extract, Undecane, Tridecane, Argania Spinosa (Argan) Kernel Oil, Rubus Chamaemorus (Cloudberry) Fruit Extract, Tocopherol, Persea Gratissima (Avocado) Oil, Prunus Amygdalus (Almond) Dulcis Oil, Prunus Armeniaca (Apricot) Kernel Oil, Parfum, Borago Officinalis (Borage) Seed Oil, Oenothera Biennis (Evening Primrose) Oil, Prunus Domestica (Plum) Seed Oil, Vaccinium Myrtillus (Blueberry) Seed Oil, Linalool, Limonene, Citronellol, Geraniol"},
        "creme": {"texte": "Crème de nuit barrière aux céramides", "actif_phare": "Céramides Végétaux", "id": 191919191919, "image": "", "safe_grossesse": True, "inci": "Jus de feuille d'Aloe Barbadensis (Aloe), Beurre de graines de Theobroma Cacao (Cacao), Huile de graines de Simmondsia Chinensis (Jojoba), Huile de graines d'Helianthus Annuus (Tournesol), Carbonate de dicaprylyle, Pentylène glycol, Stéarate de polyglycéryl-6, Alcool cétéarylique, Glycérine, Cire de graines d'Helianthus Annuus (Tournesol), Beurre de Butyrospermum Parkii (Karité), Insaponifiables d'huile d'Olea Europaea (Olive), PCA de sodium, Acide palmitique, Acide stéarique, Béhénate de polyglycéryl-6, Parfum, Cellulose, Cire d'écorce de Rhus Verniciflua / Cire de fruit de Rhus Succedanea, Résine de Shorea Robusta, Hippophae Rhamnoides (Argousier) Extrait de fruit, Gomme xanthane, Extrait de racine de Paeonia lactiflora (Pivoine), Extrait de fruit de Sambucus nigra (Sureau noir), Huile de graines de Vaccinium macrocarpon (Canneberge), Glycosphingolipides, Glycolipides, Aqua, Phytate de sodium, Palmitate d'ascorbyle, Tocophérol, Acide lactique, Hyaluronate de sodium, Linalol, Limonène"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "actif_phare": "Filtres Minéraux", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Céramides Végétaux", "Prébiotiques (Lactobacillus)", "Huile d'Argousier", "Jus d'Aloe Vera"]
    }
}

SERUM_UNIVERSEL = {"texte": "Sérum Universel Hydratation Profonde", "actif_phare": "Acide Hyaluronique Pur", "id": 999999888888, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis Leaf Juice, Sodium Hyaluronate (Multi-Molecular Weight), Panthenol, Glycerin, Pentylene Glycol."}

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
    
    pourcentage = BAUMANN_PCT.get(code, 5.5)

    return {
        "code": code,
        "pourcentage": pourcentage,
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

def generer_analyse_claude(prenom, age, profil, profil_secondaire, attentes, contexte, baumann_code, bible, scores_dict, ia_raw_scores, produits_str):
    
    photo_context = ""
    if ia_raw_scores:
        photo_context = (
            f"L'analyse photo montre (sur 100) : Rides {ia_raw_scores.get('rides', 'N/A')}, Taches {ia_raw_scores.get('taches', 'N/A')}, "
            f"Rougeurs {ia_raw_scores.get('rougeurs', 'N/A')}, Pores {ia_raw_scores.get('pores', 'N/A')}."
        )

    prompt_system = f"""Tu es le conseiller beauté personnel et scientifique de Juvea Paris.
RÈGLE ABSOLUE 1 : Ton ton doit être très chaleureux, fluide et accessible, mais tu dois te baser sur une véritable expertise technique dermatologique vulgarisée pour justifier les produits.
RÈGLE ABSOLUE 2 : Utilise le prénom ({prenom}) pour créer un lien intime.
BASE JUVEA : {bible}
PRODUITS RECOMMANDÉS (Utilise ces listes INCI pour justifier l'efficacité en mots simples dans la partie 'action scientifique') : 
{produits_str}

STRUCTURE JSON EXACTE REQUISE (Respecte scrupuleusement les clés) :
{{
  "analyse_pro": "STRICTEMENT 2 PHRASES MAXIMUM (environ 20 mots). Exemple: 'Bonjour {prenom} 🌿 Face à la météo actuelle ({contexte}), votre peau {baumann_code} a besoin d'être accompagnée. Découvrez le décryptage de votre écosystème ci-dessous.' AUCUN DÉTAIL SCIENTIFIQUE ICI.",
  "deep_dive": [
    {{
      "titre": "Pourquoi votre peau réagit-elle ainsi en ce moment ?",
      "contenu": "Explication biologique vulgarisée du comportement de sa peau ({baumann_code}) face à la météo ({contexte})."
    }},
    {{
      "titre": "Le point sur vos besoins ciblés",
      "contenu": "Explication technique et bienveillante sur la raison de ses problématiques principales ({profil} et {profil_secondaire}). {photo_context}"
    }},
    {{
      "titre": "L'action scientifique de votre rituel",
      "contenu": "Pourquoi les actifs de la routine recommandée sont biologiquement adaptés à son écosystème cutané actuel."
    }}
  ],
  "focus_actif": "1 paragraphe résumant l'avantage des actifs de sa routine.",
  "conseils_vie": "1 paragraphe bienveillant de conseils lifestyle (eau, sommeil, alimentation) adaptés à sa pathologie et la météo.",
  "exclusions_texte": "1 paragraphe court expliquant scientifiquement mais doucement quels ingrédients éviter pour ne pas empirer son profil {baumann_code}.",
  "decryptage_inci": "1 phrase rassurante expliquant que chez Juvea, on remplace l'eau inactive par du Pur Jus d'Aloe Vera bio pour une hydratation cellulaire active."
}}
IMPORTANT : Renvoie UNIQUEMENT un objet JSON valide. Utilise '\\n' pour les sauts de ligne. AUCUN vrai retour à la ligne dans le JSON."""
    
    prompt_user = f"Client: {prenom}, {age} ans. Typologie: {baumann_code}. Environnement: {contexte}. Rédige une expertise."
    
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    
    payload = {
        "model": "claude-sonnet-4-6", # Note technique : Ce modèle Anthropic n'existe pas officiellement, si ça plante, remplace-le par "claude-3-5-sonnet-20240620"
        "max_tokens": 3000, 
        "temperature": 0.6, 
        "system": prompt_system, 
        "messages": [
            {"role": "user", "content": prompt_user}
        ]
    }
    
    fallback = {
        "analyse_pro": f"Bonjour {prenom} 🌿 L'impact de la météo actuelle ({contexte}) influe directement sur votre peau {baumann_code}. Découvrez notre décryptage complet de votre écosystème cutané juste en-dessous.",
        "deep_dive": [
            {"titre": "Comprendre l'état de votre peau", "contenu": f"La typologie {baumann_code} est particulièrement sensible aux variations climatiques. Votre barrière cutanée demande une nutrition spécifique pour compenser les pertes en eau."}
        ],
        "focus_actif": "Nous avons sélectionné des alternatives végétales très douces mais ultra-efficaces qui vont gorger votre peau des nutriments dont elle a besoin.",
        "conseils_vie": f"N'oubliez pas de boire beaucoup d'eau pour contrer la météo ({contexte}) et de vous accorder de vraies nuits de sommeil, {prenom}.",
        "exclusions_texte": "Essayez de mettre de côté les nettoyants trop moussants et les produits contenant de l'alcool, qui ont tendance à assécher votre peau.",
        "decryptage_inci": f"Pour vous offrir le meilleur, {prenom}, nous avons remplacé l'eau classique de vos soins par du pur Jus d'Aloe Vera bio, ultra-hydratant."
    }
    
    try:
        if not ANTHROPIC_API_KEY: return fallback
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            raw_text = r.json()["content"][0]["text"]
            clean_text = raw_text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{[\s\S]*\}', clean_text)
            if match: 
                try: return json.loads(match.group(0))
                except Exception: pass
    except Exception: pass
    
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
    
    noms_produits = [f"- {p['texte']} (INCI: {p.get('inci', 'Aloe Barbadensis Leaf Juice')})" for p in comp]
    produits_str = "\n".join(noms_produits)
    
    txt_ia = generer_analyse_claude(prenom, age, noms.get(p1, p1), noms.get(p2, p2), ", ".join(attentes), ctx, baumann_data["code"], BIBLE_JUVEA, s_dict, ia_raw_scores, produits_str)
    actifs = list(set(cb.get("actifs", []) + cs.get("actifs", [])))
    return txt_ia, ess, comp, actifs, baumann_data

@app.post("/api/diagnostic")
def diagnostic(client: RequeteClient, request: Request, background_tasks: BackgroundTasks):
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
        
        txt_ia, ess, comp, actifs, baumann_data = generer_rituel_juvea(client.scores, client.attentes, client.exclusions, client.prenom, client.age, client_ip, client.environnement, client.ia_raw_scores)
        
        res = {
            "client": f"{client.prenom} {client.nom}",
            "baumann_code": baumann_data["code"], "baumann_pourcentage": baumann_data.get("pourcentage", 5.5), "baumann_profil": baumann_data["profil"], "baumann_explication": baumann_data["explication"], "baumann_avantages": baumann_data["avantages"], "baumann_a_fuir": baumann_data["a_fuir"],
            "analyse_pro": txt_ia.get("analyse_pro", ""), "deep_dive": txt_ia.get("deep_dive", []), "focus_actif": txt_ia.get("focus_actif", ""), "conseils_vie": txt_ia.get("conseils_vie", ""), "exclusions_texte": txt_ia.get("exclusions_texte", ""), "decryptage_inci": txt_ia.get("decryptage_inci", ""),
            "offre_essentielle": ess, "offre_complete": comp, "actifs_recommandes": actifs,
            "ia_raw_scores": client.ia_raw_scores
        }
        background_tasks.add_task(synchroniser_externe, client, txt_ia.get("analyse_pro", ""), baumann_data["code"])
        return res
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

@app.post("/api/sos-peau")
def sos_peau_chat(req: SosRequete):
    if not ANTHROPIC_API_KEY:
        return {"reponse": "Clé API Anthropic manquante sur le serveur."}
        
    nom_client = req.prenom if req.prenom else "Client"
    
    prompt_system = f"""Tu es l'Expert Dermo-Cosmétique d'Urgence Juvea Paris.
Patient : {nom_client}, Profil Baumann : {req.baumann_code} ({req.baumann_profil}).
Localisation/Météo : {req.environnement}.
RÈGLES ABSOLUES :
1. Commence toujours ta réponse par "Bonjour {nom_client},"
2. NE GÉNÈRE AUCUN FORMATAGE MARKDOWN. Rédige uniquement en texte brut.
3. Ton ton doit être clinique et expert, mais vulgarisé.
4. Base tes conseils sur le profil Baumann.
"""
    
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    content_block = []
    if req.image_b64:
        b64_clean = req.image_b64.split(",")[-1] if "," in req.image_b64 else req.image_b64
        content_block.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_clean}})
    content_block.append({"type": "text", "text": req.message})

    payload = {"model": "claude-sonnet-4-6", "max_tokens": 500, "temperature": 0.5, "system": prompt_system, "messages": [{"role": "user", "content": content_block}]}
    
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            return {"reponse": r.json()["content"][0]["text"].replace("**", "").replace("*", "").replace("#", "")}
        else: return {"reponse": f"ERREUR CLAUDE : Code {r.status_code}"}
    except Exception as e: return {"reponse": f"ERREUR SERVEUR : {str(e)}"}

@app.post("/api/scan-inci")
def scan_inci_vision(req: InciRequete):
    if not ANTHROPIC_API_KEY: return {"error": "Clé API Anthropic manquante.", "statut": "erreur"}
    cat_str = json.dumps(CATALOGUE, ensure_ascii=False)
    prompt_system = f"Analyse l'image INCI pour le type {req.baumann_code}. Recommande via : {cat_str}. JSON uniquement."
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    b64_clean = req.image_b64.split(",")[-1] if "," in req.image_b64 else req.image_b64
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 800, "system": prompt_system, "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_clean}}, {"type": "text", "text": "Analyse INCI."}]}]}
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=30)
        if r.status_code == 200: return json.loads(r.json()["content"][0]["text"])
        else: return {"statut": "erreur", "analyse": f"ERREUR CLAUDE"}
    except Exception as e: return {"statut": "erreur", "analyse": f"ERREUR SERVEUR"}