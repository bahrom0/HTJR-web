from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_compiled_web_client_serves_assets_and_spa_routes(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div><script src="/assets/app.js"></script>', encoding="utf-8")
    (assets / "app.js").write_text("console.log('ready')", encoding="utf-8")
    (assets / "app.css").write_text("body { color: black; }", encoding="utf-8")

    with TestClient(create_app(web_dist=dist)) as client:
        route_response = client.get("/capture")
        script_response = client.get("/assets/app.js")
        style_response = client.get("/assets/app.css")
        api_response = client.get("/api/v1/not-a-route")

    assert route_response.status_code == 200
    assert 'id="root"' in route_response.text
    assert script_response.headers["content-type"].startswith("application/javascript")
    assert style_response.headers["content-type"].startswith("text/css")
    assert api_response.status_code == 404
