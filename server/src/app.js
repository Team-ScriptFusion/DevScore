import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import { env } from './config/env.js';
import { configurePassport } from './config/passport.js';
import authRoutes from './routes/authRoutes.js';
import resumeRoutes from './routes/resumeRoutes.js';
import adminRoutes from './routes/adminRoutes.js';
import recruiterRoutes from './routes/recruiterRoutes.js';
import jobRoutes from './routes/jobRoutes.js';
import { notFound, errorHandler } from './middleware/errorHandler.js';

/** Build the Express application (Application Logic Tier, SDS §2.1). */
export function createApp() {
  const app = express();

  app.use(cors({ origin: env.clientUrl, credentials: true }));
  app.use(express.json());
  app.use(cookieParser());
  app.use(configurePassport().initialize());

  app.get('/api/health', (req, res) => res.json({ status: 'ok' }));
  app.use('/api/auth', authRoutes);
  app.use('/api/resume', resumeRoutes);
  app.use('/api/admin', adminRoutes);
  app.use('/api/recruiter', recruiterRoutes);
  app.use('/api/jobs', jobRoutes);

  app.use(notFound);
  app.use(errorHandler);

  return app;
}
