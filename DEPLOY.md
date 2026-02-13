# Deployment Instructions

This backend is configured for deployment on **Render** (recommended) or **Railway**, as it requires a persistent worker process and Redis for background tasks (Celery).

## Option 1: Render (Recommended)

1. **Push your code** to a GitHub/GitLab repository.
2. Log in to [Render.com](https://render.com).
3. Click "New +" and select **"Blueprint"**.
4. Connect your repository.
5. Render will detect the `render.yaml` file and automatically propose creating:
   - **acecpas-backend**: The API service.
   - **acecpas-worker**: The background task worker.
   - **acecpas-redis**: The Redis instance.
6. **Environment Variables**: You will be prompted to enter value for the following:
   - `SUPABASE_URL`
   - `SUPABASE_KEY` (Anon key)
   - `SUPABASE_SERVICE_KEY` (Service role key)
   - `OPENAI_API_KEY`
7. Click **Apply**.
8. Once deployed, copy the **Service URL** of `acecpas-backend` (e.g., `https://acecpas-backend.onrender.com`).
9. Update your **Frontend** environment variables on Vercel:
   - Set `NEXT_PUBLIC_API_URL` (or your equivalent var) to this new URL.

## Option 2: Railway

1. Log in to [Railway.app](https://railway.app).
2. Create a "New Project" -> "Deploy from GitHub repo".
3. Select your repository.
4. Add a **Redis** service to the project.
5. In the **Variables** tab for your backend service:
   - Add `REDIS_URL` (use the connection string from the Redis service).
   - Add `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, `OPENAI_API_KEY`.
   - Add `PORT` (Railway sets this automatically, but good to know).
6. **Worker Service**:
   - Go to "Settings" -> "Service" -> "New Service" -> "GitHub Repo" (select same repo).
   - In "Settings" -> "Build" -> "Start Command", enter:
     `celery -A app.workers.celery_app worker --loglevel=info`
   - Ensure it has the same Environment Variables as the backend.

## Why not Vercel?
Vercel is optimized for Serverless functions. Your backend uses **Celery** and **Redis** for long-running background tasks (file uploads, AI processing), which are not supported in a standard serverless environment. Render/Railway provide the necessary persistent processes.
