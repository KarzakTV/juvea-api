import os
import requests
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# 1. Initialisation de Firebase Admin SDK via le fichier secret
def initialiser_firebase():
    if not firebase_admin._apps:
        # On vérifie que le fichier JSON est bien présent sur le serveur Render
        if os.path.exists("firebase-cle.json"):
            cred = credentials.Certificate("firebase-cle.json")
            firebase_admin.initialize_app(cred)
            print("✅ Firebase initialisé avec succès via la clé JSON dans le scheduler.")
        else:
            print("❌ ERREUR CRITIQUE : Le fichier 'firebase-cle.json' est introuvable sur le serveur.")
            # Fallback pour éviter un crash net, même si ça échouera sans variable
            firebase_admin.initialize_app()

initialiser_firebase()
db = firestore.client()

def verifier_cycles_et_pollution():
    print("Démarrage du Robot Sentinelle : Cycles de 28 jours & Qualité de l'Air...")
    users_ref = db.collection('users')
    docs = users_ref.stream()

    aujourd_hui = datetime.now(timezone.utc)
    notifs_cycle = 0
    notifs_pollution = 0

    for doc in docs:
        user_data = doc.to_dict()
        fcm_token = user_data.get('fcmToken')
        prenom = user_data.get('prenom', 'Beauté')
        
        # Si l'utilisatrice n'a pas accepté les notifications, on passe à la suivante
        if not fcm_token:
            continue

        # =======================================================
        # MISSION 1 : CYCLE CELLULAIRE (28 JOURS)
        # =======================================================
        last_scan_str = user_data.get('lastScanDate')
        if last_scan_str:
            try:
                # Formatage de la date ISO pour Python
                if last_scan_str.endswith('Z'):
                    last_scan_str = last_scan_str[:-1] + '+00:00'
                last_scan = datetime.fromisoformat(last_scan_str)
                
                # Calcul du temps écoulé depuis la dernière expertise
                diff = aujourd_hui - last_scan
                
                # Si le cycle de 28 jours est atteint (marge de 24h)
                if 28 <= diff.days < 29:
                    message = messaging.Message(
                        notification=messaging.Notification(
                            title="Votre écosystème cutané a évolué 🔬",
                            body=f"Bonjour {prenom}, votre cycle cellulaire de 28 jours est terminé. Il est temps de mettre à jour votre expertise beauté.",
                        ),
                        token=fcm_token,
                    )
                    response = messaging.send(message)
                    print(f"✅ Push (Cycle) envoyé à {prenom} - ID: {response}")
                    notifs_cycle += 1
            except Exception as e:
                print(f"⚠️ Erreur lors du calcul du cycle pour {doc.id}: {str(e)}")

        # =======================================================
        # MISSION 2 : ALERTE POLLUTION (PM2.5 > 25)
        # =======================================================
        lat = user_data.get('latitude')
        lon = user_data.get('longitude')

        if lat and lon:
            try:
                # Interrogation de l'API Open-Meteo pour les coordonnées exactes de l'utilisatrice
                url_air = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm2_5"
                res = requests.get(url_air, timeout=5)
                
                if res.status_code == 200:
                    data = res.json()
                    pm25 = data.get('current', {}).get('pm2_5', 0)
                    
                    if pm25 > 25:
                        message_air = messaging.Message(
                            notification=messaging.Notification(
                                title="Alerte Qualité de l'Air ⚠️",
                                body=f"{prenom}, l'air est toxique dans votre zone (PM2.5: {pm25}). Pensez au double nettoyage ce soir et appliquez vos antioxydants !",
                            ),
                            token=fcm_token,
                        )
                        response_air = messaging.send(message_air)
                        print(f"🌫️ Push (Pollution) envoyé à {prenom} - ID: {response_air}")
                        notifs_pollution += 1
            except Exception as e:
                print(f"⚠️ Erreur lors de l'analyse pollution pour {doc.id}: {str(e)}")

    print(f"Vérification terminée avec succès. Notifications envoyées -> Cycle: {notifs_cycle} | Pollution: {notifs_pollution}")

if __name__ == "__main__":
    verifier_cycles_et_pollution()