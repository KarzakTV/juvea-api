from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
import os
import requests

webhook_router = APIRouter()

def get_firestore_client():
    """Initialise Firebase avec le Pass VIP officiel (Fichier JSON)"""
    if not firebase_admin._apps:
        # On vérifie que le fichier JSON est bien présent sur le serveur Heroku
        if os.path.exists("firebase-cle.json"):
            cred = credentials.Certificate("firebase-cle.json")
            firebase_admin.initialize_app(cred)
            print("✅ Firebase initialisé avec succès via la clé JSON.")
        else:
            print("❌ ERREUR CRITIQUE : Le fichier 'firebase-cle.json' est introuvable sur le serveur.")
            # Fallback (qui échouera probablement sur Heroku sans variable d'environnement, mais évite le crash net)
            firebase_admin.initialize_app()
    
    return firestore.client()

def process_shopify_order(order_data: dict):
    """
    Fonction qui traduit les données brutes de Shopify en un format 
    lisible pour notre application mobile Juvea.
    """
    try:
        # On se connecte à Firebase en présentant notre fichier JSON
        db = get_firestore_client()
    except Exception as e:
        print(f"❌ ERREUR FIREBASE : Impossible de s'authentifier. Détails : {e}")
        return

    raw_email = order_data.get("email")
    if not raw_email:
        print("Commande ignorée : Aucun e-mail rattaché.")
        return

    # Nettoyage de l'e-mail (minuscules + suppression des espaces)
    email = raw_email.strip().lower()

    # 1. Nettoyage et préparation des articles (Items)
    items = []
    for line in order_data.get("line_items", []):
        items.append({
            "name": line.get("title", "Soin Botanique"),
            "qty": line.get("quantity", 1),
            "price": str(line.get("price", "0.00"))
        })

    # 2. Formatage des données principales de la commande
    order_id = str(order_data.get("order_number", ""))
    
    raw_date = order_data.get("created_at", datetime.now().isoformat())
    clean_date = raw_date.replace("Z", "+00:00") if "T" in raw_date else raw_date
    try:
        date_obj = datetime.fromisoformat(clean_date)
        date_str = date_obj.strftime("%d %B %Y")
    except:
        date_str = "Date récente"

    tracking_url = order_data.get("order_status_url", "#")
    invoice_url = order_data.get("order_status_url", "#") 

    # --- GESTION DYNAMIQUE DU STATUT ---
    fulfillment_status = order_data.get("fulfillment_status")
    app_status = "En cours"
    
    if fulfillment_status == "fulfilled":
        app_status = "Livrée"

    # 3. Création du bloc Commande
    formatted_order = {
        "id": order_id,
        "date": date_str,
        "status": app_status,
        "total": str(order_data.get("total_price", "0.00")),
        "items": items,
        "trackingUrl": tracking_url,
        "invoiceUrl": invoice_url
    }

    # 4. Injection dans Firebase
    try:
        users_ref = db.collection("users")
        query = users_ref.where(filter=FieldFilter("email", "==", email))
        docs = query.stream()

        user_found = False
        for doc in docs:
            user_found = True
            user_data = doc.to_dict()
            current_orders = user_data.get("orders", [])
            
            # --- MISE À JOUR SI LA COMMANDE EXISTE DÉJÀ ---
            order_exists = False
            for i, o in enumerate(current_orders):
                if o.get("id") == order_id:
                    order_exists = True
                    # On remplace l'ancienne commande par la nouvelle (qui a le nouveau statut)
                    current_orders[i] = formatted_order
                    break
            
            if not order_exists:
                current_orders.insert(0, formatted_order) 
                print(f"✅ Succès : Commande #{order_id} créée pour l'utilisateur {email}.")
            else:
                print(f"🔄 Succès : Commande #{order_id} mise à jour (Statut: {app_status}) pour {email}.")
                
            # On envoie la liste actualisée à Firebase
            doc.reference.update({"orders": current_orders})

        if not user_found:
            print(f"Webhook ignoré : L'e-mail {email} n'a pas de compte sur l'application.")

    except Exception as e:
        print(f"Erreur lors de la synchronisation avec Firestore : {e}")

@webhook_router.post("/orders")
async def order_created(request: Request, background_tasks: BackgroundTasks):
    try:
        order_data = await request.json()
        background_tasks.add_task(process_shopify_order, order_data)
        return {"status": "success", "message": "Commande bien reçue, traitement en cours"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- NOUVELLE ROUTE : SUPPRESSION DE COMPTE SHOPIFY ---
@webhook_router.post("/delete-account")
async def delete_account(request: Request):
    try:
        data = await request.json()
        email = data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email manquant")
        
        # On réutilise le même token que dans le main.py
        SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "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")
        SHOP_URL = "https://juvea-3.myshopify.com/admin/api/2024-01"

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": SHOPIFY_TOKEN
        }

        # 1. Rechercher le client par email pour obtenir son ID Shopify
        search_url = f"{SHOP_URL}/customers/search.json?query=email:{email}"
        response = requests.get(search_url, headers=headers)
        
        if response.status_code == 200:
            customers = response.json().get("customers", [])
            if customers:
                customer_id = customers[0]["id"]
                
                # 2. Supprimer le client avec son ID
                delete_url = f"{SHOP_URL}/customers/{customer_id}.json"
                del_response = requests.delete(delete_url, headers=headers)
                
                if del_response.status_code == 200:
                    return {"status": "success", "message": "Compte client supprimé de Shopify"}
                else:
                    return {"status": "error", "message": "Échec de la suppression sur Shopify"}
            else:
                return {"status": "partial", "message": "Client introuvable sur Shopify (déjà supprimé ou inexistant)"}
        else:
            return {"status": "error", "message": "Erreur lors de la recherche du client Shopify"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}