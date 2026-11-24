import { createLogger, defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'PDF_AGENT_DEV_');
  const key = env.PDF_AGENT_DEV_TLS_KEY_PEM;
  const cert = env.PDF_AGENT_DEV_TLS_CERT_PEM;
  if (Boolean(key) !== Boolean(cert)) throw new Error('Configure both Vite TLS PEM values.');
  const backend = env.PDF_AGENT_DEV_BACKEND ?? 'http://127.0.0.1:8000';
  const logger = createLogger();
  const logError = logger.error;
  logger.error = (message, options) => {
    if (/(?:http|ws) proxy error:/.test(message)) {
      logError('Local API proxy request failed.');
      return;
    }
    logError(message, options);
  };
  return {
    plugins: [react()],
    customLogger: logger,
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      https: key && cert ? { key, cert } : undefined,
      proxy: { '^/sessions(?:/|$)': backend, '^/health$': backend },
    },
  };
});
