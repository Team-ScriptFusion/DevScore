import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext.jsx';
import { SearchProvider } from './context/SearchContext.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import PageTransition from './components/PageTransition.jsx';
import Home from './pages/Home.jsx';
import Login from './pages/Login.jsx';
import Signup from './pages/Signup.jsx';
import AuthCallback from './pages/AuthCallback.jsx';
import StudentDashboard from './pages/StudentDashboard.jsx';
import ConnectGithub from './pages/ConnectGithub.jsx';
import UploadResume from './pages/UploadResume.jsx';
import SkillsStatus from './pages/SkillsStatus.jsx';
import BrowseJobs from './pages/BrowseJobs.jsx';
import RecruiterDashboard from './pages/RecruiterDashboard.jsx';
import RecruiterJobs from './pages/RecruiterJobs.jsx';
import CandidateProfile from './pages/CandidateProfile.jsx';
import AdminDashboard from './pages/AdminDashboard.jsx';
import NotFound from './pages/NotFound.jsx';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        {/*
          Above <Routes> on purpose: a page claims the topbar search box by
          calling useSearch() in its own body, which runs before the
          DashboardLayout it returns has mounted. A provider inside the layout
          would be a descendant of the very component reading it.
        */}
        <SearchProvider>
          <PageTransition>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route path="/auth/callback" element={<AuthCallback />} />

              {/* Role-based access control (FR 6) enforced per route */}
              <Route
                path="/student"
                element={
                  <ProtectedRoute allow={['student']}>
                    <StudentDashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/student/jobs"
                element={
                  <ProtectedRoute allow={['student']}>
                    <BrowseJobs />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/student/github"
                element={
                  <ProtectedRoute allow={['student']}>
                    <ConnectGithub />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/student/resume"
                element={
                  <ProtectedRoute allow={['student']}>
                    <UploadResume />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/student/skills"
                element={
                  <ProtectedRoute allow={['student']}>
                    <SkillsStatus />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/recruiter"
                element={
                  <ProtectedRoute allow={['recruiter']}>
                    <RecruiterDashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/recruiter/jobs"
                element={
                  <ProtectedRoute allow={['recruiter']}>
                    <RecruiterJobs />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/recruiter/candidates/:id"
                element={
                  <ProtectedRoute allow={['recruiter']}>
                    <CandidateProfile />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute allow={['admin']}>
                    <AdminDashboard />
                  </ProtectedRoute>
                }
              />

              <Route path="*" element={<NotFound />} />
            </Routes>
          </PageTransition>
        </SearchProvider>
      </BrowserRouter>
    </AuthProvider>
  );
}
