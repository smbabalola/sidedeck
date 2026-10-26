import { ErrorBoundary } from "./components/ErrorBoundary";
import { Shell } from "./components/Shell";
import { useRoute } from "./lib/router";
import { useTheme } from "./lib/theme";
import Markets from "./workspaces/Markets";
import { Operations, Portfolio } from "./workspaces/Operations";
import Engine from "./workspaces/Engine";
import Overview from "./workspaces/Overview";
import { Agents, Strategies } from "./workspaces/Research";
import Tracks from "./workspaces/Tracks";
import DayTrader from "./workspaces/DayTrader";
import "./index.css";

export default function App() {
  const route = useRoute();
  const [theme, toggleTheme] = useTheme();
  const views = {
    overview: <Overview/>,
    engine: <Engine/>,
    markets: <Markets detail={route.detail}/>,
    tracks: <Tracks detail={route.detail}/>,
    agents: <Agents/>,
    strategies: <Strategies/>,
    portfolio: <Portfolio/>,
    operations: <Operations/>,
    "day-trader": <DayTrader/>,
  } as const;
  return <Shell active={route.workspace} theme={theme} onToggleTheme={toggleTheme}>
    <ErrorBoundary resetKey={route.workspace + (route.detail ?? "")}>{views[route.workspace]}</ErrorBoundary>
  </Shell>;
}
