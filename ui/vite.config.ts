import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output is static files (dist/), served from the storage account behind Front Door.
// No Node server needed in prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
