import os
import requests
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore, messaging

# 1. Initialisation de Firebase Admin SDK avec la clé en dur
def initialiser_firebase():
    if not firebase_admin._apps:
        # Dictionnaire contenant les identifiants de ton compte de service Firebase
        cred_dict = {
          "type": "service_account",
          "project_id": "juvea-paris",
          "private_key_id": "de09344aec8984ceed87864b542a8a66d7b83861",
          "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQDXkDCvPPA8FaDg\nQX1xDfJJsXMH5pb92D1LXxh7P4x7EjnSCR1K+IykWI4vLuCGWFbuFPMIZzLeK2ZR\nNnDvYiLGoC3y8eywbbtAtcay9oAQyQ5DdqyPAIThL3OhR13m39QAqCSDUU+63M4g\nWJ2xXDPH0+ajrAQiMb2tsqpEWy/pMJSzfuFJsGkED7KMffT7tyykG8p8I5Sq58/V\nEY2niCgkWK0ZzREh/YQZJMe9mH8qn1lxqHvFLqSphfTCSqfpA1UG7ISWo/F0G7Rx\n+TaOz4VYiVd/3/s/vC1/Ys9tOjnyrdcESnDm0KJCJ92BKTyTrhVZAH5Tjq4dslZG\nLdWUV4E9AgMBAAECggEAAfx14Mar6jEDBoK/Kpf0jZnGA89fDXxp08RofknSwn29\nP/JuDVDWqOf/YJXRVn0nYrIZa10m3C9KfGdgqU/+UbxL/ny2QwmyMgsxIL9Oy3jM\nYEvbLkXuTRqp39VMWyV6USQ7eLGt2jyqsiRNSNy4eTgHKSbOjFfor1pIIXE1DI3t\n9Vsero69tlAx6yJnsYZNLaJjl/oYmmlfTq+rPAtPhoww0YPe0UPE+Dto3AZeK+o2\nEycF8ZefxbmUop8KjvMCECkaIf3gRjaDyBuGs6TawjR+zMN7BFb1pTpmqTFM0yXI\n7J8QtgliU/nOc5DvqxN8X0Xvf6gQd/qFO5Rr63TEAQKBgQDtHE+YJzdFJCVxJsQ7\nq67hd4EpDug/bxrFNXBSQC0EZg4SW8cpk/7QeNBD8kyRFmqHT+Vy4ZOAV9FoPGF8\nXBks115uSPGI1mGdnbFycimJzDaKl9vGLSjP3vY+/FFKsnfMj3ooBc1Y9/JLqcey\n2Cb6+wgI66oalacaAGMIf9TVPQKBgQDovHAHB6CvmwVPm7nsjh8Zyl5KiDhlG2v9\n/IFdGhgFQhF4jG0USY3q2Dx7C9SyVLz/K56TtCirjvbZjahmVargs1URtNFvTEUw\nMWWWNg+xSjUUZq3Ab7SWls1QPLI89g8MuMbRIm4Hncv+2Xwa2BmZL9IaeQPKDc23\nTUB3tPAcAQKBgQDUTG/7xMkY8BdSK6qx3rNzjuOnloBeI6Wtg35xNqLX+GSLDX/S\ne39Au5uF6tGhapexVdkUNmMyG+8UTFPg3DlyS9dyGX+hzImUbVgvJ4aHqb//8Z5G\n37JWBMUoehRzND5Nev2eDivhiAd6taZnPGASgmecTR1+NhZrEoOZXZN75QKBgQDM\nVHR+l4HJ6u40wGHxf61qdTNneEUa74JWkRP6a2hfZWv1TESQJSvF3WbsGKz6jE8K\nMH+e6fMy++dZhXctsVS+xnOPghLGBk5QS24G/Ru16ZLEgIlXhDsmYuuK4F8UCmuY\nHbnf7rxvT2jELKk64DNJPKTXvRtIj+nmXpqU/nQ4AQKBgQCUTrJSe4NFszvTckl/\njBTobVXZ+66A0422y/CYog1aqt5NUpqvSSo02iWTQDiG6GVfm+hycxzCtBLf9HTs\na4JmDU9YCuH7CubbimH6nvsJzq6bSw5YcklyZxrob/KhDknnJTI+8Pkm72E7PUcO\nvreGTiImNyVa2y3Aye3fxqFSlg==\n-----END PRIVATE KEY-----\n",
          "client_email": "firebase-adminsdk-fbsvc@juvea-paris.iam.gserviceaccount.com",
          "client_id": "103644239787035728384",
          "auth_uri": "https://accounts.google.com/o/oauth2/auth",
          "token_uri": "https://oauth2.googleapis.com/token",
          "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
          "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40juvea-paris.iam.gserviceaccount.com",
          "universe_domain": "googleapis.com"
        }
        
        try:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Erreur critique: Impossible d'initialiser Firebase avec le dictionnaire. Détails : {e}")
            exit(1)

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