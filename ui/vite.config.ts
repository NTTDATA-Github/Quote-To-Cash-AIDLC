import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output is static files (dist/) — deploy straight to an S3 bucket configured
// for static website hosting, or behind CloudFront. No Node server needed in prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
