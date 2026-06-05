from dotenv import load_dotenv

load_dotenv()


def main():
    print("NovelScript Backend Server starting...")
    import uvicorn, os

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=os.getenv("DEBUG", False),
        reload_dirs="app",
    )


if __name__ == "__main__":
    main()
