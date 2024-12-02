from fastapi import FastAPI, Depends, Request
from utils.l402_auth import l402_authentication

app = FastAPI()

# Protected endpoint requiring L402 authentication
@app.get("/protected-resource")
async def protected_resource(request: Request, auth=Depends(l402_authentication)):
    return {"message": "Welcome to the protected resource! Your payment has been verified."}

