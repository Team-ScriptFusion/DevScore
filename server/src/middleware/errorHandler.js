import { env } from '../config/env.js';

/** 404 handler for unmatched routes. */
export function notFound(req, res) {
  res.status(404).json({ error: `Route not found: ${req.method} ${req.path}` });
}

/** Centralised error handler — logs and returns a safe JSON error. */
// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, _next) {
  console.error('[error]', err);

  if (err.name === 'MulterError') {
    const message =
      err.code === 'LIMIT_FILE_SIZE'
        ? 'Resume must be 5MB or smaller'
        : 'Could not process the uploaded file';
    return res.status(400).json({ error: message });
  }

  const status = err.status || 500;
  res.status(status).json({
    error: err.expose ? err.message : 'Internal server error',
    ...(env.nodeEnv === 'development' ? { detail: err.message } : {}),
  });
}
