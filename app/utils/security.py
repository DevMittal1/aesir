import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)

def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify that the payload matches the signature sent by Meta.
    
    Meta sends an X-Hub-Signature-256 header in the format:
    sha256=abcdef123456...
    
    This is an HMAC SHA256 hex digest of the raw request body using the App Secret as the key.
    """
    if not signature_header:
        logger.error("X-Hub-Signature-256 header is missing.")
        return False
        
    if not signature_header.startswith("sha256="):
        logger.error(f"X-Hub-Signature-256 header is in incorrect format: {signature_header}")
        return False
        
    # Extract signature from header (everything after 'sha256=')
    header_signature = signature_header[7:]
    
    # Compute signature
    computed_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Compare digests securely to avoid timing attacks
    if not hmac.compare_digest(computed_signature, header_signature):
        logger.error("Signature verification failed. Signatures do not match.")
        return False
        
    return True
