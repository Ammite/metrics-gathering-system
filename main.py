from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime, Integer
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from datetime import datetime
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

os.makedirs("database", exist_ok=True)
DATABASE_URL = "sqlite:///./database/metrics.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class MetricDB(Base):
    __tablename__ = "metrics"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    uid = Column(String, index=True)
    source = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class MetricCreate(BaseModel):
    uid: str
    source: str

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def read_metrics_page(request: Request, db: Session = Depends(get_db)):
    metrics = db.query(MetricDB).order_by(MetricDB.created_at.desc()).all()
    return templates.TemplateResponse("metrics.html", {"request": request, "metrics": metrics})

@app.post("/metrics")
def create_metric(metric: MetricCreate, db: Session = Depends(get_db)):
    db_metric = MetricDB(**metric.model_dump())
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    return {"status": "success", "metric_id": db_metric.id, "uid": db_metric.uid}

@app.delete("/metrics/{metric_id}")
def delete_metric(metric_id: int, db: Session = Depends(get_db)):
    metric = db.query(MetricDB).filter(MetricDB.id == metric_id).first()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    db.delete(metric)
    db.commit()
    return {"status": "success", "message": f"Metric with ID {metric_id} deleted"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)