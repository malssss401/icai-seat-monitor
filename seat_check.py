import requests
from bs4 import BeautifulSoup
import os

URL = "https://www.icaionlineregistration.org/launchbatchdetail.aspx"

PUSHOVER_USER = os.environ["PUSHOVER_USER"]
PUSHOVER_TOKEN = os.environ["PUSHOVER_TOKEN"]

def send_notification(message):
    requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "message": message
        }
    )

def check_seats():

    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(URL, headers=headers)

    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.find_all("tr")

    for row in rows:

        cols = [c.text.strip() for c in row.find_all("td")]

        for col in cols:

            if col.isdigit():

                seats = int(col)

                if seats > 0:

                    send_notification(f"🚨 ICAI seats available! {seats} seats open.")
                    return True

    return False


if __name__ == "__main__":

    if check_seats():
        print("Seats available!")
    else:
        print("No seats yet.")
