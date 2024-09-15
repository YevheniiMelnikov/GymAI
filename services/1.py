import binascii
import hashlib
import hmac
from datetime import datetime


def generate_signature(dt: str, login: str, payee_id: str, shop_order_number: str, bill_amount: str, key: str) -> str:
    str_to_sign = payee_id + dt + binascii.hexlify(shop_order_number.encode()).decode().upper() + bill_amount
    str_to_sign = str_to_sign.upper() + binascii.hexlify(login.encode()).decode().upper()
    return hmac.new(key.encode(), str_to_sign.encode(), hashlib.sha256).hexdigest().upper()


dt = datetime.now().strftime("%Y%m%d%H%M%S")
login = "EVHENII"
payee_id = "138741"
shop_order_number = "123"
bill_amount = "100"
key = "L84V5R7G8CAFTH75873V1TBU6EF9W75EA"
signature = generate_signature(dt, login, payee_id, shop_order_number, bill_amount, key)
print(dt)
print(signature)


a = {
    "paymentType": "a2c_1",
    "description": "4444333322221111",
    "billAmount": "100",
    "payeeId": "138741",
    "shopOrderNumber": "123",
    "dt": "20240915202329",
    "signature": "7EA6F24539C7D4958B7A691C3A0BAA7D5A2D03C82BF8CC4F8462CD1B15EC6318",
    "mode": "1101",
    "sender": "1101",
    "identification": {
        "sender": {
            "firstName": "Євгеній",
            "lastName": "Мельников",
            "account_number": "UA273510050000026002879161058",
        },
        "senderAddress": {
            "countryCode": "UKR",
            "city": "Kyiv",
            "address": "вул. Пимоненка, 13",
        },
        "recipient": {
            "dstFirstName": "Test",
            "dstLastName": "Test",
            "tax_id": "1111111111",
        },
    },
}
