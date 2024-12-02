import os
import base64

def generate_secret_key():
    key = os.urandom(32)  # 256-bit key
    return base64.urlsafe_b64encode(key).decode('utf-8')

# Generate and print the secret key
if __name__ == "__main__":
    secret_key = generate_secret_key()
    print(f"Your secure macaroon secret key:\n{secret_key}")

