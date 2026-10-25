"""Flask entry point for the SQLite-backed Wu pronunciation site."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from search import SearchService


BASE_DIRECTORY = Path(__file__).resolve().parent


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(BASE_DIRECTORY / "fonts"),static_url_path="/fonts",)
    service = SearchService(BASE_DIRECTORY / "data")

    @app.after_request
    def disable_api_cache(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIRECTORY, "templates/index.html")

    @app.get("/data/<path:filename>")
    def data_file(filename: str):
        """詞彙查詢彈窗在瀏覽器端直接抓 S2T.json／siqyin_dict.json（與靜態版同法）。"""
        return send_from_directory(BASE_DIRECTORY / "data", filename)

    @app.post("/api/search")
    def search_characters():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text", "")
        dialects = payload.get("dialects")
        include_dictionary = payload.get("dictionary", False)
        if not isinstance(text, str):
            return jsonify({"error": "text must be a string"}), 400
        if dialects is not None and not isinstance(dialects, list):
            return jsonify({"error": "dialects must be a list"}), 400
        if not isinstance(include_dictionary, bool):
            return jsonify({"error": "dictionary must be a boolean"}), 400
        try:
            return jsonify(
                service.search_characters(
                    text, dialects, include_dictionary
                )
            )
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

    @app.post("/api/pinyin")
    def search_pinyin():
        payload = request.get_json(silent=True) or {}
        pinyin = payload.get("pinyin", "")
        if not isinstance(pinyin, str):
            return jsonify({"error": "pinyin must be a string"}), 400
        try:
            return jsonify(service.reverse_lookup(pinyin))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

    @app.post("/api/yuntu_pos")
    def yuntu_pos():
        try:
            return jsonify(service.yuntu_positions())
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

    return app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("WUGNIU_HOST", "127.0.0.1")
    port = int(os.environ.get("WUGNIU_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
