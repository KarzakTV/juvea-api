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
NOTRE SECRET DE FORMULATION : Nous remplaçons souvent l'eau inactive par du Pur Jus d'Aloe Vera certifié bio.
NOS ACTIFS PHARES : Bidens Pilosa, Lactobacillus Ferment, Acide Glycolique & Salicylique.
TON : Empathique, luxueux, clinique, sur-mesure.
"""

CATALOGUE = {
    "purete": {
        "nettoyant": {"texte": "Soin anti-acné", "id": 111111111111, "image": "", "safe_grossesse": False, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Kaolin, Argania Spinosa (Argan) Kernel Oil, Melaleuca Alternifolia (Tea Tree) Leaf Oil, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Isoamyl Laurate, Salicylic Acid, Sodium PCA, Propanediol, Potassium Hydroxide, Xanthan Gum, Polyglyceryl-6 Behenate, Parfum/Fragrance, Cellulose, Palmitic Acid, Stearic Acid, Aqua/Water, Rhodomyrtus Tomentosa (Rose Myrtle) Fruit Extract, Ribes Grossularia (Gooseberry) Fruit Extract, Vaccinium Myrtillus (Blueberry) Fruit Extract, Ascorbyl Palmitate, Tocopherol, Charcoal Powder, Limonene, Citral, Linalool, Citronellol, Geraniol"},
        "lotion": {"texte": "Lotion Tonique Exfoliante à l'Acide Glycolique", "id": 222222222222, "image": "", "safe_grossesse": False, "inci": "Aqua, Glycolic Acid, Glycerin, Potassium Hydroxide, Betaine, Sodium PCA, Sodium Levulinate, Phenethyl Alcohol, Sodium Benzoate, Vaccinium Macrocarpon (Cranberry) Fruit Extract, Vaccinium Vitis-Idaea (Lingonberry) Fruit Extract, Alcohol"},
        "serum": {"texte": "Sérum Gel Niacinamide", "id": 333333333333, "image": "", "safe_grossesse": True, "inci": "Aqua/Water, Alcohol, Niacinamide, Glycerin, Cellulose Gum, Algin, Potassium Hydroxide, Parfum/Fragrance, Sodium Phytate, Ginkgo Biloba (Ginkgo) Leaf Extract, Citric Acid, Sodium Benzoate, Potassium Sorbate"},
        "creme": {"texte": "Gel Hydratant Sans Huile", "id": 444444444444, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Pentylene Glycol, Butylene Glycol, Betaine, Sclerotium Gum, Zinc PCA, Aqua, Propanediol, Parfum, Nasturtium Officinale (Watercress) Flower/Leaf Extract, Sodium Phytate, Potassium Hydroxide, Sodium Hyaluronate, Rhamnose, Glucose, Glucuronic Acid, Limonene, Linalool, Geraniol, Citral"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Acide Salicylique", "Zinc PCA", "Acide Glycolique", "Huile d'Arbre à Thé", "Niacinamide"]
    },
    "temps": {
        "nettoyant": {"texte": "Lait Nettoyant Doux", "id": 666666666666, "image": "", "safe_grossesse": True, "inci": "Aqua, Helianthus Annuus (Sunflower) Seed Oil, Sucrose Distearate, Glycerin, Dicaprylyl Carbonate, Isoamyl Laurate, Sucrose Stearate, Butyrospermum Parkii (Shea) Butter, Sodium Levulinate, Palmitic Acid, Stearic Acid, Xanthan Gum, Parfum, Sodium Anisate, Argania Spinosa (Argan) Kernel Oil, Persea Gratissima (Avocado) Oil, Simmondsia Chinensis (Jojoba) Seed Oil, Lactic Acid, Centaurea Cyanus (Cornflower) Flower Extract, Paeonia Lactiflora (Peony) Root Extract, Ascorbyl Palmitate, Sodium Phytate, Tocopherol, Linalool, Limonene, Benzyl Salicylate, Citral"},
        "lotion": {"texte": "Gel Booster Double Hydratation + AH", "id": 777777777777, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Pentylene Glycol, Butylene Glycol, Glycerin, Sodium PCA, Aqua/Water, Propanediol, Cellulose Gum, Parfum/Fragrance, Algin, Camellia Sinensis (White Tea) Leaf Extract, Salvia Officinalis (Sage) Leaf Extract, Hydrolyzed Hyaluronic Acid, Lactic Acid, Sodium Hyaluronate, Sodium Phytate, Rhamnose, Glucose, Glucuronic Acid"},
        "serum": {"texte": "Crème hydratante alternative au rétinol", "id": 888888888888, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Simmondsia Chinensis (Jojoba) Seed Oil, Glycerin, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Aqua/Water, Sodium PCA, Dipalmitoyl Hydroxyproline, Astrocaryum Murumuru Seed Butter, Hippophae Rhamnoides (Sea Buckthorn) Fruit Extract, Gossypium Herbaceum Seed Oil, Propanediol, Bidens Pilosa Extract, Dicaprylyl Carbonate, Polyglyceryl-6 Behenate, Parfum/Fragrance, Linum Usitatissimum Seed Oil, Mangifera Indica (Mango) Seed Butter, Caprylic/Capric Triglyceride, Coco-Caprylate, Xanthan Gum, Octyldodecanol, Palmitic Acid, Stearic Acid, Tocopherol, Ascorbyl Palmitate, Potassium Hydroxide, Rhodomyrtus Tomentosa (Rose Myrtle) Fruit Extract, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Sodium Phytate, Alteromonas Ferment Extract, Phenethyl Alcohol, Geraniol, Citronellol, Pelargonium Graveolens Flower Oil, Linalool, Citral"},
        "yeux": {"texte": "Sérum contour des yeux alternatif au rétinol", "id": 999999999999, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Glycerin, Coconut Alkanes, Pentylene Glycol, Aqua/Water, Simmondsia Chinensis (Jojoba) Seed Oil, Sodium PCA, Polyglyceryl-6 Stearate, Glyceryl Stearate Citrate, Borago Officinalis (Borage) Seed Oil, Caprylic/Capric Triglyceride, Dipalmitoyl Hydroxyproline, Ricinus Communis (Castor) Seed Oil, Astrocaryum Murumuru Seed Butter, Gossypium Herbaceum Seed Oil, Bidens Pilosa Extract, Linum Usitatissimum Seed Oil, Parfum/Fragrance, CI 77163 (Bismuth Chloride Oxide), Polyglyceryl-6 Behenate, Rhus Verniciflua Peel Cera/Rhus Succedanea Fruit Cera, Xanthan Gum, Aesculus Hippocastanum (Horse Chestnut) Seed Extract, Cellulose, Tocopherol, Ascorbyl Palmitate, Potassium Hydroxide, Mangifera Indica (Mango) Seed Butter, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Sodium Phytate, Octyldodecanol, Alteromonas Ferment Extract, Phenethyl Alcohol, Escin, Geraniol, Citronellol, Pelargonium Graveolens Flower Oil, Linalool, Citral"},
        "creme": {"texte": "Crème de jour anti-âge", "id": 101010101010, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Simmondsia Chinensis (Jojoba) Seed Oil, Glycerin, Pentylene Glycol, Polyglyceryl-6 Stearate, Cetearyl Alcohol, Betaine, Isoamyl Laurate, Aqua, Butyrospermum Parkii (Shea) Butter, Parfum, Caprylic/Capric Triglyceride, Polyglyceryl-6 Behenate, Cellulose, CI 77891 (Titanium Dioxide), Mica, Palmitic Acid, Stearic Acid, Vaccinium Vitis-Idaea (Lingonberry) Fruit Extract, Xanthan Gum, Echinacea Purpurea (Coneflower) Flower/Leaf/Stem Extract, Ribes Nigrum (Black Currant) Fruit Extract, Sambucus Nigra (Elder) Flower Extract, Ascorbyl Palmitate, Persea Gratissima (Avocado) Oil, Tocopherol, Hydrolyzed Hyaluronic Acid, Potassium Hydroxide, Sodium Hyaluronate, Sodium Phytate, Alteromonas Ferment Extract, Phenethyl Alcohol, Tin Oxide, Alcohol, Benzyl Salicylate, Limonene, Citral, Linalool"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Phyto-Rétinol (Bidens Pilosa)", "Acide Hyaluronique", "Sève de Bouleau", "Escine"]
    },
    "eclat": {
        "nettoyant": {"texte": "Nettoyant visage éclat radieux", "id": 121212121212, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Coco-Glucoside, Cocamidopropyl Betaine, Glycerin, Aqua/Water, Xanthan Gum, Propanediol, Rubus Fruticosus (Blackberry) Fruit Extract, Sodium PCA, Sodium Levulinate, Lactic Acid, Acacia Senegal Gum, Sodium Anisate, Acorus Calamus (Sweet Flag) Root Extract, Parfum/Fragrance, Salvia Officinalis (Sage) Leaf Extract, Rhamnose, CI 77491 (Iron Oxides), Glucose, Glucuronic Acid, Arctium Lappa (Burdock) Root Extract, Citric Acid, Sodium Benzoate, Potassium Sorbate, Linalool, Limonene"},
        "lotion": {"texte": "Concentré Peeling AHA", "id": 131313131313, "image": "", "safe_grossesse": False, "inci": "Aqua/Water, Lactic Acid, Pentylene Glycol, Potassium Hydroxide, Butylene Glycol, Glycerin, Sodium Hyaluronate, Camellia Sinensis (White Tea) Leaf Extract, Salvia Officinalis (Sage) Leaf Extract"},
        "serum": {"texte": "Sérum perfecteur de pigment", "id": 141414141414, "image": "", "safe_grossesse": False, "inci": "Aqua, Glycerin, Caprylic/Capric Triglyceride, Helianthus Annuus (Sunflower) Seed Oil, Pentylene Glycol, Cetearyl Alcohol, Sodium PCA, Glyceryl Stearate Citrate, Alpha-Arbutin, Astrocaryum Murumuru Seed Butter, Gossypium Herbaceum Seed Oil, Bidens Pilosa Extract, Cellulose, Linum Usitatissimum Seed Oil, Parfum, Xanthan Gum, Ascorbyl Palmitate, Lactic Acid, Ascophyllum Nodosum Extract, Sodium Phytate, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Tocopherol, Limonene, Citrus Limon Peel Oil, Pogostemon Cablin Oil, Linalool, Juniperus Virginiana Oil, Cedrus Atlantica Oil/Extract, Pinene, Vanillin, Menthol, Citral, Beta-Caryophyllene"},
        "creme": {"texte": "Gel Booster au ginkgo antioxydant", "id": 151515151515, "image": "", "safe_grossesse": True, "inci": "Aqua, Alcohol, Glycerin, Carrageenan, Cellulose Gum, Ceratonia Siliqua Gum, Parfum, Glucose, Ginkgo Biloba (Ginkgo) Leaf Extract, Citric Acid, Sodium Phytate, Camellia Sinensis (Green Tea) Leaf Extract, Potassium Hydroxide, Quercus Robur (Oak) Bark Extract, Vitis Vinifera (Grape) Seed Extract, Sodium Benzoate, Potassium Sorbate"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Alpha-Arbutine", "Acides de Fruits (AHA)", "Ginkgo Biloba", "Vitamine C"]
    },
    "apaisement": {
        "nettoyant": {"texte": "Démaquillant BiPhasic, sans parfum", "id": 161616161616, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis (Aloe) Leaf Juice, Isoamyl Laurate, Coco-Caprylate/Caprate, Butylene Glycol, Glycerin, Coconut Alkanes, Sodium Chloride, Aqua, Sodium Levulinate, Tocopherol, Sodium Benzoate, Caprylyl/Capryl Glucoside, Lactic Acid, Sodium Phytate, Chamomilla Recutita (Camomile) Flower Extract, Hippophae Rhamnoides (Sea-Buckthorn) Fruit Extract, Rubus Idaeus (Raspberry) Fruit Extract, Capsicum Annuum (Paprika) Fruit Extract, Sodium Hyaluronate, Helianthus Annuus (Sunflower) Seed Oil, Citric Acid, Potassium Sorbate, Rosmarinus Officinalis (Rosemary) Leaf Extract"},
        "serum": {"texte": "Sérum Gel aux Prébiotiques Bioactifs", "id": 171717171717, "image": "", "safe_grossesse": True, "inci": "Aqua/Water, Alcohol, Glycerin, Sodium PCA, Cellulose Gum, Algin, Lactobacillus Ferment Lysate, Parfum/Fragrance, Sodium Phytate, Potassium Sorbate, Sodium Benzoate, Hydrolyzed Hyaluronic Acid, Sodium Hyaluronate, Pogostemon Cablin Oil"},
        "huile": {"texte": "Huile visage nourrissante", "id": 181818181818, "image": "", "safe_grossesse": True, "inci": "Simmondsia Chinensis (Jojoba) Seed Oil, Decyl Cocoate, Solanum Lycopersicum (Tomato) Fruit Extract, Hippophae Rhamnoides (Sea Buckthorn) Fruit Extract, Undecane, Tridecane, Argania Spinosa (Argan) Kernel Oil, Rubus Chamaemorus (Cloudberry) Fruit Extract, Tocopherol, Persea Gratissima (Avocado) Oil, Prunus Amygdalus (Almond) Dulcis Oil, Prunus Armeniaca (Apricot) Kernel Oil, Parfum, Borago Officinalis (Borage) Seed Oil, Oenothera Biennis (Evening Primrose) Oil, Prunus Domestica (Plum) Seed Oil, Vaccinium Myrtillus (Blueberry) Seed Oil, Linalool, Limonene, Citronellol, Geraniol"},
        "creme": {"texte": "Crème de nuit barrière aux céramides", "id": 191919191919, "image": "", "safe_grossesse": True, "inci": "Jus de feuille d'Aloe Barbadensis (Aloe), Beurre de graines de Theobroma Cacao (Cacao), Huile de graines de Simmondsia Chinensis (Jojoba), Huile de graines d'Helianthus Annuus (Tournesol), Carbonate de dicaprylyle, Pentylène glycol, Stéarate de polyglycéryl-6, Alcool cétéarylique, Glycérine, Cire de graines d'Helianthus Annuus (Tournesol), Beurre de Butyrospermum Parkii (Karité), Insaponifiables d'huile d'Olea Europaea (Olive), PCA de sodium, Acide palmitique, Acide stéarique, Béhénate de polyglycéryl-6, Parfum, Cellulose, Cire d'écorce de Rhus Verniciflua / Cire de fruit de Rhus Succedanea, Résine de Shorea Robusta, Hippophae Rhamnoides (Argousier) Extrait de fruit, Gomme xanthane, Extrait de racine de Paeonia lactiflora (Pivoine), Extrait de fruit de Sambucus nigra (Sureau noir), Huile de graines de Vaccinium macrocarpon (Canneberge), Glycosphingolipides, Glycolipides, Aqua, Phytate de sodium, Palmitate d'ascorbyle, Tocophérol, Acide lactique, Hyaluronate de sodium, Linalol, Limonène"},
        "spf": {"texte": "Protection solaire SPF50 Stick, avec teinte", "id": 555555555555, "image": "", "safe_grossesse": True, "inci": "Zinc Oxide, Oryza Sativa (Rice) Bran Oil, Vegetable Oil, Dicaprylyl Carbonate, Isoamyl Laurate, CI 77891 (Titanium Dioxide), Helianthus Annuus (Sunflower) Seed Wax, Oryza Sativa (Rice) Bran Wax, Rhus Succedanea Fruit Wax, Hydrated Silica, Simmondsia Chinensis (Jojoba) Seed Oil, Silica, Jojoba Esters, Theobroma Cacao (Cocoa) Seed Butter, Parfum/Fragrance, Tocopherol, Hippophae Rhamnoides (Sea Buckthorn) Fruit Oil, Nigella Sativa (Black Cumin) Seed Oil, CI 77491, CI 77492, CI 77499 (Iron Oxides), Glycolipids, Glycosphingolipids, Aqua/Water, Vanillin, Terpineol, Linalyl Acetate, Anethole, Geraniol"},
        "actifs": ["Céramides Végétaux", "Prébiotiques (Lactobacillus)", "Huile d'Argousier", "Jus d'Aloe Vera"]
    }
}

SERUM_UNIVERSEL = {"texte": "Sérum Universel Hydratation Profonde", "id": 999999888888, "image": "", "safe_grossesse": True, "inci": "Aloe Barbadensis Leaf Juice, Sodium Hyaluronate (Multi-Molecular Weight), Panthenol, Glycerin, Pentylene Glycol."}

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

def generer_analyse_claude(prenom, age, profil, profil_secondaire, attentes, contexte, baumann_code, bible, scores_dict, ia_raw_scores, produits_str):
    
    photo_context = ""
    if ia_raw_scores:
        photo_context = (
            f"La note IA de la caméra biométrique indique (sur 100) : Rides {ia_raw_scores.get('rides', 'N/A')}, Taches {ia_raw_scores.get('taches', 'N/A')}, "
            f"Rougeurs {ia_raw_scores.get('rougeurs', 'N/A')}, Pores {ia_raw_scores.get('pores', 'N/A')}. Utilise ces données pour prouver ton analyse de façon simple."
        )

    prompt_system = f"""Tu es l'IA Experte en Dermo-Cosmétique de Juvea Paris.
RÈGLE ABSOLUE 1 : Ne propose JAMAIS de consulter un cabinet physique Juvea. Ne propose un médecin que si la situation est grave.
RÈGLE ABSOLUE 2 : Ton ton est LUXUEUX, RASSURANT, PERSONNALISÉ et PÉDAGOGIQUE. Utilise le prénom du client ({prenom}) pour t'adresser directement à lui (ex: "Bonjour {prenom}, à {age} ans..."). Vulgarise les termes scientifiques compliqués (parle de "barrière protectrice" au lieu de termes médicaux trop poussés).
RÈGLE ABSOLUE 3 : Tu dois être CONCIS, IMPACTANT et ALLER À L'ESSENTIEL.
BASE DE CONNAISSANCES JUVEA :
{bible}
PRODUITS JUVEA SÉLECTIONNÉS POUR CE CLIENT ET LEURS INCI (Sers-toi de ces listes INCI pour justifier tes choix) : 
{produits_str}

STRUCTURE JSON EXACTE REQUISE :
{{
  "analyse_pro": "1 à 2 paragraphes maximum s'adressant à {prenom}. Explique simplement comment son âge, la météo ({contexte}) et sa typologie ({baumann_code}) affectent sa peau ({profil}, {profil_secondaire}). Explique pourquoi la routine de soins est la solution idéale pour lui. {photo_context}",
  "focus_actif": "1 paragraphe synthétique vulgarisant l'action des actifs (en t'appuyant explicitement sur les listes INCI fournies) présents dans les produits recommandés ci-dessus.",
  "conseils_vie": "1 paragraphe court sur l'hygiène de vie et la météo s'adressant à {prenom}.",
  "exclusions_texte": "1 paragraphe court proscrivant les ingrédients irritants de façon simple.",
  "decryptage_inci": "1 phrase claire expliquant à {prenom} que nous utilisons des ingrédients de qualité et que le premier ingrédient INCI est souvent l'Aloe Vera plutôt que l'eau."
}}
IMPORTANT : Renvoie UNIQUEMENT un objet JSON valide. Tu dois IMPÉRATIVEMENT utiliser '\\n' pour les sauts de ligne à l'intérieur de tes valeurs. NE FAIS AUCUN VRAI RETOUR À LA LIGNE dans les chaînes de caractères du JSON."""
    
    prompt_user = f"Client: {prenom}, {age} ans. Typologie: {baumann_code}. Environnement: {contexte}. Rédige l'expertise vulgarisée et personnalisée en justifiant avec les INCI."
    
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2500, 
        "temperature": 0.5, 
        "system": prompt_system, 
        "messages": [
            {"role": "user", "content": prompt_user}
        ]
    }
    
    fallback = {
        "analyse_pro": f"Bonjour {prenom}, vos marqueurs liés à votre âge ({age} ans) et votre environnement ({contexte}) indiquent que votre barrière protectrice est fragilisée, ce qui accentue les problèmes liés à {profil}. Votre typologie {baumann_code} le confirme. C'est pourquoi les soins formulés sur-mesure sont parfaits pour consolider les fondations de votre peau.",
        "focus_actif": "Les alternatives végétales hautement dosées de vos produits agissent directement au cœur de vos cellules pour des résultats visibles.",
        "conseils_vie": f"Protégez-vous des agressions climatiques ({contexte}) et veillez à avoir un sommeil réparateur, {prenom}.",
        "exclusions_texte": "Évitez absolument l'utilisation de nettoyants trop agressifs qui décapent votre peau.",
        "decryptage_inci": f"Chez Juvea, {prenom}, l'eau inactive est souvent remplacée par du Jus d'Aloe Vera bio en premier ingrédient INCI pour vous offrir une hydratation maximale."
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
                except Exception as parse_err:
                    print(f"❌ Erreur lors du parsing JSON de Claude : {parse_err}", flush=True)
                    print(f"Texte brut renvoyé par Claude :\n{clean_text}", flush=True)
                    pass
            else:
                print(f"❌ Regex n'a pas trouvé de JSON valide. Texte brut :\n{clean_text}", flush=True)
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
    
    # FORMATAGE INCI POUR CLAUDE
    # On extrait les noms des produits + leur INCI pour que Claude puisse les mentionner
    noms_produits = [f"- {p['texte']} (INCI: {p.get('inci', 'Aloe Barbadensis Leaf Juice, Actifs naturels')})" for p in comp]
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
def sos_peau_chat(req: SosRequete):
    if not ANTHROPIC_API_KEY:
        return {"reponse": "Clé API Anthropic manquante sur le serveur."}
        
    nom_client = req.prenom if req.prenom else "Client"
    
    prompt_system = f"""Tu es l'Expert Dermo-Cosmétique d'Urgence Juvea Paris.
Patient : {nom_client}, Profil Baumann : {req.baumann_code} ({req.baumann_profil}).
Localisation/Météo : {req.environnement}.

RÈGLES ABSOLUES :
1. Commence toujours ta réponse par "Bonjour {nom_client},"
2. NE GÉNÈRE AUCUN FORMATAGE MARKDOWN (pas de gras, pas d'astérisques **, pas de titres #). Rédige uniquement en texte brut.
3. Ton ton doit être clinique et expert, mais vulgarisé pour être compréhensible par le client.
4. Base tes conseils strictement sur le profil Baumann du client.
5. Si le client envoie une photo de sa peau, analyse visuellement la problématique (rougeurs, boutons, sécheresse, etc.) et intègre cette observation à ton conseil.
6. Si le problème décrit ou visible sur la photo nécessite une expertise médicale (maladie de peau, infection, acné sévère, lésion suspecte), signale-le impérativement.
7. Dans ce cas médical, utilise la localisation du client ({req.environnement}) pour proposer des spécialistes (dermatologues ou cliniques) autour de lui SI tu en connais de réputés dans cette zone. Si tu n'en trouves pas de précis dans cette zone, indique clairement que tu n'as pas trouvé de spécialiste à proximité immédiate dans ta base et invite le client à se renseigner par lui-même.
"""
    
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    
    content_block = []
    if req.image_b64:
        b64_clean = req.image_b64.split(",")[-1] if "," in req.image_b64 else req.image_b64
        content_block.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64_clean
            }
        })
    
    content_block.append({"type": "text", "text": req.message})

    payload = {
        "model": "claude-sonnet-4-6", 
        "max_tokens": 500, 
        "temperature": 0.5, 
        "system": prompt_system, 
        "messages": [{"role": "user", "content": content_block}]
    }
    
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            texte_brut = r.json()["content"][0]["text"]
            texte_propre = texte_brut.replace("**", "").replace("*", "").replace("#", "")
            return {"reponse": texte_propre}
        else:
            print(f"❌ Erreur API SOS Peau: {r.status_code} - {r.text}", flush=True)
            return {"reponse": f"ERREUR CLAUDE : Code {r.status_code} - {r.text}"}
    except Exception as e:
        print(f"❌ Exception API SOS Peau: {e}", flush=True)
        return {"reponse": f"ERREUR SERVEUR : {str(e)}"}

@app.post("/api/scan-inci")
def scan_inci_vision(req: InciRequete):
    if not ANTHROPIC_API_KEY:
        return {"error": "Clé API Anthropic manquante.", "statut": "erreur", "analyse": "Clé API manquante sur le serveur."}
        
    cat_str = json.dumps(CATALOGUE, ensure_ascii=False)
    prompt_system = f"Analyse l'image INCI pour le type {req.baumann_code}. Recommande via : {cat_str}. JSON uniquement."
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    b64_clean = req.image_b64.split(",")[-1] if "," in req.image_b64 else req.image_b64
    payload = {"model": "claude-sonnet-4-6", "max_tokens": 800, "system": prompt_system, "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_clean}}, {"type": "text", "text": "Analyse INCI."}]}]}
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