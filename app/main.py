from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.db.config import SessionLocal, Base, engine
from app.api.routes import api_router



app = FastAPI()

app.include_router(api_router, prefix="/api/v1")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root(db: Session = Depends(get_db)):
    return {"msg": "Conexión a PostgreSQL funcionando"}
