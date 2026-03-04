import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import { CallList } from './components/CallList';
import { CallTimelineView } from './components/CallTimeline';

export function App() {
  return (
    <BrowserRouter>
      <header className="app-header">
        <h1>Call Flow Visualizer</h1>
        <nav>
          <Link to="/">Calls</Link>
        </nav>
      </header>
      <div className="container">
        <Routes>
          <Route path="/" element={<CallList />} />
          <Route path="/calls/:callId" element={<CallTimelineView />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
