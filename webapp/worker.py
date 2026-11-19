"""Worker d'alerting (module G) — squelette, développé en semaine 6."""
import time

if __name__ == "__main__":
    print("alert-worker démarré (aucune règle évaluée pour l'instant)", flush=True)
    while True:
        time.sleep(60)
