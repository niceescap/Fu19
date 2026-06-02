# Exemple de ce que fera l'Agent API (Ne pas coder tout de suite !)
@app.post("/api/auth/request")
def http_request_login(payload: LoginSchema, db: Session = Depends(get_db)):
    # L'API appelle notre brique
    linker.request_login(db, payload.email)
    return {"message": "Si le compte existe, un email a été envoyé."}

@app.get("/auth/verify")
def http_verify_landing(token: str, email: str, db: Session = Depends(get_db)):
    # L'API vérifie le clic
    success = linker.process_landing(db, email, token)
    if success:
        # Ici l'API crée le cookie et redirige vers le Dashboard
        return RedirectResponse(url="/dashboard", headers=create_session_cookie(email))
    return TemplateResponse("error_token.html")
