from fastapi import FastAPI, HTTPException, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, String, DateTime, Integer, func
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from datetime import datetime, date
from typing import Optional, List, Dict
import os
from config import settings

app = FastAPI()

# Добавляем CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем все домены для разработки
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Добавляем middleware для сессий
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

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

def check_auth(request: Request):
    """Проверяет авторизацию пользователя"""
    return request.session.get("authenticated") == True

def require_auth(request: Request):
    """Требует авторизации для доступа"""
    if not check_auth(request):
        raise HTTPException(status_code=401, detail="Authentication required")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Страница входа"""
    if check_auth(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Обработка авторизации"""
    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=302)
    else:
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "Неверный логин или пароль"
        })

@app.get("/logout")
def logout(request: Request):
    """Выход из системы"""
    request.session.pop("authenticated", None)
    return RedirectResponse(url="/login", status_code=302)

@app.get("/", response_class=HTMLResponse)
def read_metrics_page(
    request: Request, 
    db: Session = Depends(get_db),
    source_filter: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None)
):
    # Проверяем авторизацию
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=302)
    
    query = db.query(MetricDB)
    
    # Применяем фильтры
    if source_filter:
        query = query.filter(MetricDB.source == source_filter)
    
    if date_from:
        query = query.filter(MetricDB.created_at >= date_from)
    
    if date_to:
        # Добавляем один день, чтобы включить весь день date_to
        from datetime import timedelta
        query = query.filter(MetricDB.created_at < date_to + timedelta(days=1))
    
    metrics = query.order_by(MetricDB.created_at.desc()).all()
    
    # Группируем метрики по событиям (uid)
    event_stats = db.query(
        MetricDB.uid,
        func.count(MetricDB.uid).label('count')
    )
    
    # Применяем те же фильтры для статистики
    if source_filter:
        event_stats = event_stats.filter(MetricDB.source == source_filter)
    
    if date_from:
        event_stats = event_stats.filter(MetricDB.created_at >= date_from)
    
    if date_to:
        from datetime import timedelta
        event_stats = event_stats.filter(MetricDB.created_at < date_to + timedelta(days=1))
    
    event_stats = event_stats.group_by(MetricDB.uid).order_by(func.count(MetricDB.uid).desc()).all()
    
    # Статистика по источникам
    source_stats = db.query(
        MetricDB.source,
        func.count(MetricDB.source).label('count')
    )
    
    # Применяем те же фильтры для статистики источников
    if source_filter:
        source_stats = source_stats.filter(MetricDB.source == source_filter)
    
    if date_from:
        source_stats = source_stats.filter(MetricDB.created_at >= date_from)
    
    if date_to:
        from datetime import timedelta
        source_stats = source_stats.filter(MetricDB.created_at < date_to + timedelta(days=1))
    
    source_stats = source_stats.group_by(MetricDB.source).order_by(func.count(MetricDB.source).desc()).all()
    
    # Получаем все доступные источники для фильтра
    all_sources = db.query(MetricDB.source).distinct().all()
    all_sources = [s[0] for s in all_sources]
    
    # Создаем воронку конверсии
    funnel_data = calculate_conversion_funnel(db, source_filter, date_from, date_to)
    
    return templates.TemplateResponse("metrics.html", {
        "request": request, 
        "metrics": metrics,
        "event_stats": event_stats,
        "source_stats": source_stats,
        "all_sources": all_sources,
        "current_source": source_filter,
        "date_from": date_from,
        "date_to": date_to,
        "total_metrics": len(metrics),
        "unique_events": len(event_stats),
        "unique_sources": len(source_stats),
        "funnel_data": funnel_data
    })

def calculate_conversion_funnel(db: Session, source_filter: Optional[str], date_from: Optional[date], date_to: Optional[date]):
    """Рассчитывает воронку конверсии для основных событий"""
    
    # Определяем этапы воронки в порядке важности согласно README
    funnel_steps = [
        {"key": "WEBSITE_OPENED", "name": "Зашел на сайт", "icon": "🌐", "color": "#10b981"},
        {"key": "MENU_OPENED", "name": "Открыл меню", "icon": "📋", "color": "#3b82f6"},
        {"key": "MENU_WHATSAPP", "name": "Нажал на WhatsApp", "icon": "📱", "color": "#25d366"},
        {"key": "MENU_TELEGRAM", "name": "Нажал на Telegram", "icon": "✈️", "color": "#0088cc"},
        {"key": "CHATBOT_OPENED", "name": "Нажал открыть чат", "icon": "💬", "color": "#667eea"},
        {"key": "CHATBOT_USER_MESSAGE", "name": "Написал в чат", "icon": "✍️", "color": "#f59e0b"},
        {"key": "CHATBOT_GET_PHONE", "name": "Получили номер телефона", "icon": "📞", "color": "#dc2626"}
    ]
    
    funnel_results = []
    
    for step in funnel_steps:
        # Базовый запрос для подсчета событий
        query = db.query(func.count(MetricDB.id)).filter(MetricDB.uid == step["key"])
        
        # Применяем фильтры
        if source_filter:
            query = query.filter(MetricDB.source == source_filter)
        
        if date_from:
            query = query.filter(MetricDB.created_at >= date_from)
        
        if date_to:
            from datetime import timedelta
            query = query.filter(MetricDB.created_at < date_to + timedelta(days=1))
        
        count = query.scalar() or 0
        
        funnel_results.append({
            "key": step["key"],
            "name": step["name"],
            "icon": step["icon"],
            "color": step["color"],
            "count": count
        })
    
    # Рассчитываем конверсии между этапами
    for i, step in enumerate(funnel_results):
        if i == 0:
            step["conversion"] = 100.0  # Первый этап - базовый (100%)
            step["width"] = 100
        else:
            # Конверсия относительно предыдущего этапа
            prev_count = funnel_results[i-1]["count"]
            if prev_count > 0:
                step["conversion"] = (step["count"] / prev_count) * 100
            else:
                step["conversion"] = 0.0
            
            # Ширина полосы для визуализации
            if funnel_results[0]["count"] > 0:
                step["width"] = (step["count"] / funnel_results[0]["count"]) * 100
            else:
                step["width"] = 0
    
    return funnel_results

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
    uvicorn.run(app, host="0.0.0.0", port=8004)