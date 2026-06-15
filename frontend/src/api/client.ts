import axios from "axios";

const api = axios.create({
  baseURL:
    import.meta.env.VITE_API_URL ||
    "https://plum-ai-claims-engine.onrender.com",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

export default api;