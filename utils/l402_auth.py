import httpx
from fastapi import HTTPException, Request, Response
import os
from dotenv import load_dotenv
import logging
import base64
from pymacaroons import Macaroon, Verifier
from datetime import datetime, timedelta
import pytz  # For timezone handling
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

LNBITS_URL = os.getenv("LNBITS_URL")
L402_KEY = os.getenv("L402_KEY")
SECRET_KEY = os.getenv("MACAROON_SECRET_KEY")

if not all([LNBITS_URL, L402_KEY, SECRET_KEY]):
    raise RuntimeError("Environment variables LNBITS_URL, L402_KEY, and MACAROON_SECRET_KEY must be set.")

# In-memory store to track used macaroons (for demonstration purposes)
# For production, consider using a persistent storage like a database (e.g., Redis)
used_macaroons = set()

async def create_invoice(amount: int):
    # Create a Lightning invoice via LNbits API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{LNBITS_URL}/api/v1/payments",
            headers={"X-Api-Key": L402_KEY},
            json={"out": False, "amount": amount, "memo": "Access Payment"}
        )
        response.raise_for_status()
        invoice_data = response.json()
        return invoice_data["payment_request"], invoice_data["payment_hash"]

async def create_macaroon_with_caveats(payment_hash: str, expiration_minutes: int, scope: str):
    # Use a Unique Identifier in Macaroon Identifier
    identifier = str(uuid.uuid4())
    # Generate a new macaroon with the payment_hash as a caveat
    macaroon = Macaroon(location="lighning_goats", identifier=identifier, key=SECRET_KEY)
    # Add payment_hash as a first-party caveat
    macaroon.add_first_party_caveat(f"payment_hash = {payment_hash}")
    # Add expiration time as a caveat
    expiration_time = (datetime.utcnow() + timedelta(minutes=expiration_minutes)).isoformat() + 'Z'
    macaroon.add_first_party_caveat(f"expiration = {expiration_time}")
    # Add scope as a caveat
    macaroon.add_first_party_caveat(f"scope = {scope}")
    return macaroon

async def verify_payment(payment_hash: str) -> bool:
    # Verify payment status using LNbits API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{LNBITS_URL}/api/v1/payments/{payment_hash}",
                headers={"X-Api-Key": L402_KEY}
            )
            response.raise_for_status()
            payment_data = response.json()
            return payment_data.get("paid", False)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=502, detail="Error verifying payment status.")
    except httpx.RequestError as e:
        logger.error(f"An error occurred while requesting the LNbits API: {e}")
        raise HTTPException(status_code=502, detail="Error verifying payment status.")

async def l402_authentication(request: Request):
    logger.info("l402_authentication called.")
    authorization: str = request.headers.get("Authorization")
    if authorization:
        logger.info("Authorization header found.")
        if not authorization.startswith("LSAT "):
            logger.error("Invalid LSAT header format.")
            raise HTTPException(status_code=401, detail="Invalid LSAT header format.")

        # Extract the serialized macaroon
        _, serialized_macaroon = authorization.split(" ", 1)
        try:
            # No need to base64 decode; the serialized_macaroon is already in the correct format
            macaroon = Macaroon.deserialize(serialized_macaroon)
            logger.info("Macaroon deserialized successfully.")
        except Exception as e:
            logger.error(f"Failed to deserialize macaroon: {e}")
            raise HTTPException(status_code=400, detail="Invalid macaroon.")

        # Initialize variables for caveats
        payment_hash = None
        expiration_time = None
        scope = None

        # Extract caveats from the macaroon
        for caveat in macaroon.caveats:
            if caveat.caveat_id.startswith("payment_hash = "):
                payment_hash = caveat.caveat_id.split(" = ", 1)[1]
            elif caveat.caveat_id.startswith("expiration = "):
                expiration_time = caveat.caveat_id.split(" = ", 1)[1]
            elif caveat.caveat_id.startswith("scope = "):
                scope = caveat.caveat_id.split(" = ", 1)[1]

        # Validate presence of all required caveats
        missing_caveats = []
        if not payment_hash:
            missing_caveats.append("payment_hash")
        if not expiration_time:
            missing_caveats.append("expiration")
        if not scope:
            missing_caveats.append("scope")
        if missing_caveats:
            logger.error(f"Macaroon missing caveats: {', '.join(missing_caveats)}.")
            raise HTTPException(
                status_code=401,
                detail=f"Macaroon missing caveats: {', '.join(missing_caveats)}."
            )

        # Create a verifier and satisfy the caveats
        verifier = Verifier()
        verifier.satisfy_exact(f"payment_hash = {payment_hash}")
        verifier.satisfy_exact(f"expiration = {expiration_time}")
        verifier.satisfy_exact(f"scope = {scope}")

        # Verify the macaroon's signature
        try:
            verifier.verify(macaroon, SECRET_KEY)
            logger.info("Macaroon signature verification succeeded.")
        except Exception as e:
            logger.error(f"Macaroon signature verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid macaroon signature.")

        # Verify payment
        is_paid = await verify_payment(payment_hash)
        if not is_paid:
            logger.error("Payment required but not completed.")
            raise HTTPException(status_code=402, detail="Payment required but not completed.")

        # Validate expiration time
        try:
            expiration_dt = datetime.fromisoformat(expiration_time.rstrip('Z')).replace(tzinfo=pytz.UTC)
            if datetime.utcnow().replace(tzinfo=pytz.UTC) > expiration_dt:
                logger.error("Macaroon has expired.")
                raise HTTPException(status_code=401, detail="Macaroon has expired.")
        except ValueError:
            logger.error("Invalid expiration time format.")
            raise HTTPException(status_code=400, detail="Invalid expiration time format.")

        # Validate scope
        requested_scope = request.url.path  # Get the requested path
        if scope != requested_scope:
            logger.error("Access to the requested resource is forbidden.")
            raise HTTPException(status_code=403, detail="Access to the requested resource is forbidden.")

        # Authentication successful; proceed to the endpoint
        logger.info("Authorization successful.")
        return  # Proceed to the endpoint function

    else:
        logger.info("No Authorization header found. Initiating LSAT challenge.")
        # No authorization header, initiate LSAT challenge
        amount = 1000  # Adjust amount as needed
        invoice, payment_hash = await create_invoice(amount)
        # Define the scope and expiration for the macaroon
        expiration_minutes = 30  # Macaroon valid for 30 minutes
        scope = request.url.path  # Restrict macaroon to the requested path
        macaroon = await create_macaroon_with_caveats(payment_hash, expiration_minutes, scope)
        serialized_macaroon = macaroon.serialize()
        # No additional base64 encoding is necessary
        macaroon_base64 = serialized_macaroon  # Already base64-encoded by serialize()

        # Build WWW-Authenticate header according to LSAT standards
        www_authenticate = f'LSAT macaroon="{macaroon_base64}", invoice="{invoice}"'

        # Raise an HTTPException with 402 status code and include the WWW-Authenticate header
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={"WWW-Authenticate": www_authenticate}
        )
