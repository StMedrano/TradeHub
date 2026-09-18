import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Theme,
  Box,
  Flex,
  Grid,
  Card,
  Heading,
  Text,
  Badge,
  Button,
  IconButton,
  Progress,
  Separator,
  Table,
  Callout,
  Dialog,
  TextField,
  TextArea,
  Tooltip
} from "@radix-ui/themes";
import {
  DashboardIcon,
  LightningBoltIcon,
  BackpackIcon,
  CheckCircledIcon,
  MixerHorizontalIcon,
  ActivityLogIcon,
  GearIcon,
  MagicWandIcon,
  BellIcon,
  ReloadIcon,
  ExclamationTriangleIcon,
  CheckIcon,
  Cross2Icon,
  ChevronRightIcon,
  BarChartIcon,
  LockClosedIcon,
  DotFilledIcon,
  PersonIcon,
  RocketIcon
} from "@radix-ui/react-icons";

const NAV = [
  ["overview", "Overview", DashboardIcon],
  ["opportunities", "Trade Opportunities", LightningBoltIcon],
  ["positions", "Positions", BackpackIcon],
  ["approvals", "Approvals", CheckCircledIcon],
  ["risk", "Risk & Limits", MixerHorizontalIcon],
  ["activity", "Activity", ActivityLogIcon],
  ["settings", "Settings", GearIcon],
  ["strategy", "Strategy Lab", MagicWandIcon]
];

const SECTION_COPY = {
  overview: ["Overview", "Your portfolio at a glance"],
  opportunities: ["Trade Opportunities", "Candidates produced by the strategy engine"],
  positions: ["Positions", "Open Robinhood Agentic option and equity exposure"],
  approvals: ["Approvals", "Review risk-approved trade intents before execution"],
  risk: ["Risk & Limits", "Hard portfolio limits enforced before every order"],
  activity: ["Activity", "Audit trail for decisions, approvals, pauses, and execution"],
  settings: ["Settings", "Robinhood connection and operator controls"],
  strategy: ["Strategy Lab", "Rollout phases and strategy availability"]
};

function money(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

function pct(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(1) + "%";
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function MiniSparkline({ active = false }) {
  return (
    <svg className="sparkline" viewBox="0 0 150 44" aria-hidden="true">
      <polyline
        points="0,30 18,27 34,29 51,22 67,25 83,18 101,20 117,13 132,15 150,8"
        fill="none"
        stroke={active ? "var(--green-9)" : "var(--gray-7)"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MetricCard({ label, value, detail, connected, tone = "neutral" }) {
  return (
    <Card className="metric-card">
      <Flex justify="between" align="start" gap="3">
        <Box>
          <Text size="2" color="gray">{label}</Text>
          <Heading size="6" mt="2" className={tone === "positive" ? "positive" : tone === "negative" ? "negative" : ""}>
            {value}
          </Heading>
          <Text size="1" color="gray">{detail}</Text>
        </Box>
        <MiniSparkline active={connected} />
      </Flex>
    </Card>
  );
}

function StatusPill({ summary }) {
  const mode = summary?.trading_mode === "live" ? "LIVE" : "DRY RUN";
  const connectionState = summary?.robinhood_connection_state || (summary?.robinhood_mcp_enabled ? "configured" : "disabled");
  const connectionLabels = {
    connected: "Robinhood Connected",
    degraded: "Robinhood Degraded",
    authentication_required: "Robinhood Auth Required",
    error: "Robinhood Error",
    configured: "Robinhood MCP Configured",
    disabled: "Robinhood MCP Disabled"
  };
  const connection = connectionLabels[connectionState] || connectionState;
  const connectionColor = connectionState === "connected" ? "green" : connectionState === "disabled" ? "gray" : "amber";
  return (
    <Flex align="center" gap="2" wrap="wrap">
      <Badge color={connectionColor} variant="soft" radius="full">
        <DotFilledIcon /> {connection}
      </Badge>
      <Badge color={summary?.trading_mode === "live" ? "red" : "amber"} variant="soft" radius="full">
        {mode}
      </Badge>
      <Badge color="green" variant="soft" radius="full">
        <DotFilledIcon /> System Healthy
      </Badge>
    </Flex>
  );
}

function EmptyPanel({ icon: Icon = RocketIcon, title, body, action, onAction }) {
  return (
    <Flex className="empty-panel" direction="column" align="center" justify="center" gap="3">
      <Flex className="empty-icon" align="center" justify="center">
        <Icon width="24" height="24" />
      </Flex>
      <Heading size="3">{title}</Heading>
      <Text size="2" color="gray" align="center">{body}</Text>
      {action ? <Button variant="soft" onClick={onAction}>{action}</Button> : null}
    </Flex>
  );
}

function ApprovalCards({ approvals, onAction }) {
  if (!approvals.length) {
    return (
      <EmptyPanel
        icon={CheckCircledIcon}
        title="No approvals waiting"
        body="Risk-approved trade intents will appear here before live execution."
      />
    );
  }

  return (
    <Flex direction="column" gap="3">
      {approvals.slice(0, 5).map((item) => (
        <Card key={item.id} className="approval-card">
          <Flex justify="between" gap="3" align="center" wrap="wrap">
            <Box>
              <Flex gap="2" align="center">
                <Heading size="3">{item.underlying}</Heading>
                <Badge color="green" variant="soft">{item.strategy.replaceAll("_", " ")}</Badge>
              </Flex>
              <Text size="2" color="gray">
                {item.contracts} contract(s) · Known max loss {money(item.known_max_loss)}
              </Text>
              <Text size="1" color="gray">{formatDate(item.created_at)}</Text>
            </Box>
            <Flex gap="2">
              <Button size="2" onClick={() => onAction(item, "approve")}>
                <CheckIcon /> Approve
              </Button>
              <Button size="2" color="red" variant="soft" onClick={() => onAction(item, "reject")}>
                <Cross2Icon /> Reject
              </Button>
            </Flex>
          </Flex>
        </Card>
      ))}
    </Flex>
  );
}

function ActivityTable({ activity }) {
  if (!activity.length) {
    return (
      <EmptyPanel
        icon={ActivityLogIcon}
        title="No activity yet"
        body="Trade decisions, approvals, circuit breakers, and execution events will be recorded here."
      />
    );
  }

  return (
    <div className="table-scroll">
      <Table.Root variant="surface">
        <Table.Header>
          <Table.Row>
            <Table.ColumnHeaderCell>Time</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>Event</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>Symbol</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>Message</Table.ColumnHeaderCell>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {activity.map((event) => (
            <Table.Row key={event.id}>
              <Table.Cell>{formatDate(event.created_at)}</Table.Cell>
              <Table.Cell><Badge variant="soft" color={event.severity === "warning" ? "amber" : "gray"}>{event.event_type}</Badge></Table.Cell>
              <Table.Cell>{event.underlying || "—"}</Table.Cell>
              <Table.Cell>{event.message}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Root>
    </div>
  );
}

function RiskPanel({ summary }) {
  const utilization = summary?.risk_utilization_pct ?? 0;
  const tradeLimit = (summary?.max_trade_loss_pct ?? 0.05) * 100;
  const portfolioLimit = (summary?.max_portfolio_loss_pct ?? 0.20) * 100;
  const breaker = (summary?.daily_loss_breaker_pct ?? 0.10) * 100;

  return (
    <Card className="large-card">
      <Flex justify="between" align="center" mb="4">
        <Box>
          <Heading size="4">Risk &amp; Limits</Heading>
          <Text size="2" color="gray">Hard controls checked before every order</Text>
        </Box>
        <Badge
          color={summary?.portfolio_risk_authoritative ? "green" : "amber"}
          variant="soft"
        >
          <LockClosedIcon />
          {summary?.portfolio_risk_authoritative ? "Authoritative" : "Pending Reconstruction"}
        </Badge>
      </Flex>

      {!summary?.portfolio_risk_authoritative && summary?.portfolio_risk_reasons?.length ? (
        <Callout.Root color="amber" mb="4">
          <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
          <Callout.Text>{summary.portfolio_risk_reasons.join(" · ")}</Callout.Text>
        </Callout.Root>
      ) : null}

      <Grid columns={{ initial: "1", md: "2" }} gap="5">
        <Box>
          <Flex justify="between" mb="2">
            <Text size="2">Portfolio Risk Utilization</Text>
            <Text size="2" weight="bold">{pct(utilization)}</Text>
          </Flex>
          <Progress value={Math.min(utilization, 100)} color="green" />
          <Flex justify="between" mt="2">
            <Text size="1" color="gray">Open risk {money(summary?.open_risk)}</Text>
            <Text size="1" color="gray">Cap {portfolioLimit.toFixed(0)}% equity</Text>
          </Flex>
        </Box>

        <Grid columns="3" gap="3">
          <Box className="limit-tile">
            <Text size="1" color="gray">Per trade</Text>
            <Heading size="4">{tradeLimit.toFixed(0)}%</Heading>
          </Box>
          <Box className="limit-tile">
            <Text size="1" color="gray">Portfolio</Text>
            <Heading size="4">{portfolioLimit.toFixed(0)}%</Heading>
          </Box>
          <Box className="limit-tile">
            <Text size="1" color="gray">Daily breaker</Text>
            <Heading size="4">{breaker.toFixed(0)}%</Heading>
          </Box>
        </Grid>
      </Grid>
    </Card>
  );
}

function PositionPanel({ summary }) {
  return (
    <Card className="large-card">
      <Flex justify="between" align="center" mb="4">
        <Box>
          <Heading size="4">Position Overview</Heading>
          <Text size="2" color="gray">Robinhood Agentic account exposure</Text>
        </Box>
        <Badge variant="soft" color={summary?.robinhood_connection_state === "connected" ? "green" : "gray"}>
          {summary?.robinhood_connection_state === "connected" ? "Live read sync" : "Awaiting connection"}
        </Badge>
      </Flex>

      <Grid columns={{ initial: "2", sm: "4" }} gap="3">
        <Box className="position-stat">
          <Text size="1" color="gray">Open Positions</Text>
          <Heading size="5">{summary?.open_positions ?? 0}</Heading>
        </Box>
        <Box className="position-stat">
          <Text size="1" color="gray">Open Orders</Text>
          <Heading size="5">{summary?.open_orders ?? 0}</Heading>
        </Box>
        <Box className="position-stat">
          <Text size="1" color="gray">Approvals</Text>
          <Heading size="5">{summary?.pending_approvals ?? 0}</Heading>
        </Box>
        <Box className="position-stat">
          <Text size="1" color="gray">Underlying Holds</Text>
          <Heading size="5">{summary?.paused_underlyings ?? 0}</Heading>
        </Box>
      </Grid>
    </Card>
  );
}

function Sidebar({ section, setSection, approvalCount }) {
  return (
    <aside className="sidebar">
      <Flex className="brand" align="center" gap="3">
        <Flex className="brand-mark" align="center" justify="center">
          <BarChartIcon width="20" height="20" />
        </Flex>
        <Box className="brand-text">
          <Heading size="4">TradeHub</Heading>
          <Text size="1" color="gray">Robinhood Agentic</Text>
        </Box>
      </Flex>

      <nav className="nav-list">
        {NAV.slice(0, 7).map(([key, label, Icon]) => (
          <button
            key={key}
            className={"nav-item " + (section === key ? "active" : "")}
            onClick={() => setSection(key)}
          >
            <Icon width="18" height="18" />
            <span>{label}</span>
            {key === "approvals" && approvalCount > 0 ? (
              <span className="nav-count">{approvalCount}</span>
            ) : null}
          </button>
        ))}
      </nav>

      <Separator size="4" my="4" />

      <button
        className={"nav-item " + (section === "strategy" ? "active" : "")}
        onClick={() => setSection("strategy")}
      >
        <MagicWandIcon width="18" height="18" />
        <span>Strategy Lab</span>
      </button>
    </aside>
  );
}

function ActionDialog({ state, setState, onSubmit }) {
  return (
    <Dialog.Root open={state.open} onOpenChange={(open) => setState((s) => ({ ...s, open }))}>
      <Dialog.Content maxWidth="460px">
        <Dialog.Title>{state.verb === "approve" ? "Approve trade" : "Reject trade"}</Dialog.Title>
        <Dialog.Description size="2" mb="4">
          {state.item ? state.item.underlying + " · " + state.item.strategy.replaceAll("_", " ") : ""}
        </Dialog.Description>

        <Flex direction="column" gap="3">
          <label>
            <Text as="div" size="2" weight="bold" mb="1">Operator ID</Text>
            <TextField.Root
              value={state.actor}
              placeholder="stalin"
              onChange={(e) => setState((s) => ({ ...s, actor: e.target.value }))}
            >
              <TextField.Slot><PersonIcon /></TextField.Slot>
            </TextField.Root>
          </label>

          <label>
            <Text as="div" size="2" weight="bold" mb="1">Note</Text>
            <TextArea
              value={state.note}
              placeholder="Optional approval/rejection note"
              onChange={(e) => setState((s) => ({ ...s, note: e.target.value }))}
            />
          </label>
        </Flex>

        <Flex gap="3" mt="5" justify="end">
          <Dialog.Close>
            <Button variant="soft" color="gray">Cancel</Button>
          </Dialog.Close>
          <Button
            color={state.verb === "approve" ? "green" : "red"}
            disabled={!state.actor.trim()}
            onClick={onSubmit}
          >
            {state.verb === "approve" ? <CheckIcon /> : <Cross2Icon />}
            {state.verb === "approve" ? "Approve" : "Reject"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}

export default function App() {
  const [section, setSection] = useState("overview");
  const [summary, setSummary] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [pauses, setPauses] = useState([]);
  const [activity, setActivity] = useState([]);
  const [positions, setPositions] = useState({ equities: [], options: [] });
  const [loading, setLoading] = useState(true);
  const [scanSymbol, setScanSymbol] = useState("SPY");
  const [scanResult, setScanResult] = useState(null);
  const [candidateResult, setCandidateResult] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [promotingId, setPromotingId] = useState(null);
  const [error, setError] = useState("");
  const previousApprovals = useRef(0);
  const [dialog, setDialog] = useState({
    open: false,
    item: null,
    verb: "approve",
    actor: localStorage.getItem("tradehubOperator") || "",
    note: ""
  });

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const responses = await Promise.all([
        fetch("/api/dashboard/summary"),
        fetch("/api/approvals"),
        fetch("/api/pauses"),
        fetch("/api/activity"),
        fetch("/api/positions")
      ]);

      if (responses.some((r) => !r.ok)) {
        throw new Error("TradeHub API returned an error.");
      }

      const [nextSummary, nextApprovals, nextPauses, nextActivity, nextPositions] = await Promise.all(
        responses.map((r) => r.json())
      );

      if (
        nextApprovals.length > previousApprovals.current &&
        previousApprovals.current > 0 &&
        "Notification" in window &&
        Notification.permission === "granted"
      ) {
        new Notification("TradeHub approval required", {
          body: nextApprovals.length + " trade proposal(s) are waiting."
        });
      }

      previousApprovals.current = nextApprovals.length;
      setSummary(nextSummary);
      setApprovals(nextApprovals);
      setPauses(nextPauses);
      setActivity(nextActivity);
      setPositions(nextPositions);
      setError("");
    } catch (err) {
      setError(err.message || "Unable to load TradeHub.");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(false);
    const timer = window.setInterval(() => refresh(true), 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const title = SECTION_COPY[section][0];
  const subtitle = SECTION_COPY[section][1];

  const metrics = useMemo(() => ([
    ["Total Equity", money(summary?.equity), summary?.robinhood_connection_state === "connected" ? "Robinhood Agentic" : "Connect Robinhood to populate"],
    ["Buying Power", money(summary?.buying_power), summary?.robinhood_connection_state === "connected" ? "Available capital" : "Awaiting account sync"],
    ["Today's P&L", money(summary?.daily_pnl), summary?.daily_pnl_pct == null ? "No synced P&L yet" : pct(summary.daily_pnl_pct), summary?.daily_pnl > 0 ? "positive" : summary?.daily_pnl < 0 ? "negative" : "neutral"],
    ["Total P&L", money(summary?.total_pnl), "Tracked positions", summary?.total_pnl > 0 ? "positive" : summary?.total_pnl < 0 ? "negative" : "neutral"]
  ]), [summary]);

  function openAction(item, verb) {
    setDialog((d) => ({ ...d, open: true, item, verb, note: "" }));
  }

  async function submitAction() {
    if (!dialog.item || !dialog.actor.trim()) return;
    localStorage.setItem("tradehubOperator", dialog.actor.trim());
    const response = await fetch(
      "/api/approvals/" + dialog.item.id + "/" + dialog.verb,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: dialog.actor.trim(), note: dialog.note })
      }
    );
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    setDialog((d) => ({ ...d, open: false, item: null, note: "" }));
    refresh(true);
  }

  async function acknowledgePause(symbol) {
    const actor = dialog.actor.trim() || localStorage.getItem("tradehubOperator") || "operator";
    const response = await fetch("/api/pauses/" + symbol + "/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor })
    });
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    refresh(true);
  }

  async function enableNotifications() {
    if ("Notification" in window) {
      await Notification.requestPermission();
    }
  }

  async function promoteCandidate(candidate) {
    if (!candidate?.option_id || !candidateResult?.symbol) return;
    setPromotingId(candidate.option_id);
    try {
      const response = await fetch("/api/opportunities/promote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: candidateResult.symbol,
          option_id: candidate.option_id
        })
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = body.detail;
        if (typeof detail === "object" && detail?.reasons) {
          throw new Error(detail.reasons.join(" · "));
        }
        throw new Error(
          typeof detail === "string" ? detail : "Candidate promotion failed."
        );
      }

      await refresh(true);
      await scanOptions();
      setSection("approvals");
      setError("");
    } catch (err) {
      setError(err.message || "Candidate promotion failed.");
    } finally {
      setPromotingId(null);
    }
  }

  async function scanOptions() {
    const symbol = scanSymbol.trim().toUpperCase();
    if (!symbol) return;
    setScanning(true);
    try {
      const [scanResponse, candidateResponse] = await Promise.all([
        fetch("/api/opportunities/scan?symbol=" + encodeURIComponent(symbol)),
        fetch("/api/opportunities/candidates?symbol=" + encodeURIComponent(symbol))
      ]);

      const [scanBody, candidateBody] = await Promise.all([
        scanResponse.json(),
        candidateResponse.json()
      ]);

      if (!scanResponse.ok) {
        throw new Error(scanBody.detail || "Option scan failed.");
      }
      if (!candidateResponse.ok) {
        throw new Error(candidateBody.detail || "Candidate scan failed.");
      }

      setScanResult(scanBody);
      setCandidateResult(candidateBody);
      setError("");
    } catch (err) {
      setError(err.message || "Option scan failed.");
    } finally {
      setScanning(false);
    }
  }

  function renderMain() {
    if (section === "overview") {
      return (
        <>
          <Grid columns={{ initial: "1", sm: "2", xl: "4" }} gap="4">
            {metrics.map(([label, value, detail, tone]) => (
              <MetricCard
                key={label}
                label={label}
                value={value}
                detail={detail}
                tone={tone}
                connected={summary?.robinhood_connection_state === "connected"}
              />
            ))}
          </Grid>

          <Grid className="section-grid" columns={{ initial: "1", lg: "2" }} gap="4">
            <RiskPanel summary={summary} />
            <PositionPanel summary={summary} />
          </Grid>

          <Grid className="section-grid" columns={{ initial: "1", lg: "2" }} gap="4">
            <Card className="large-card">
              <Flex justify="between" align="center" mb="4">
                <Box>
                  <Heading size="4">Trade Opportunities</Heading>
                  <Text size="2" color="gray">Strategy candidates that passed scanning</Text>
                </Box>
                <Button size="2" variant="soft" onClick={() => refresh(false)}>
                  <ReloadIcon /> Refresh
                </Button>
              </Flex>
              <EmptyPanel
                icon={LightningBoltIcon}
                title="Waiting for the strategy engine"
                body="IV rank, directional signals, liquidity, and Robinhood option-chain scoring will populate this panel."
              />
            </Card>

            <Card className="large-card">
              <Flex justify="between" align="center" mb="4">
                <Box>
                  <Heading size="4">Approvals</Heading>
                  <Text size="2" color="gray">Risk-approved trades awaiting operator action</Text>
                </Box>
                <Badge color={approvals.length ? "amber" : "green"} variant="soft">
                  {approvals.length} pending
                </Badge>
              </Flex>
              <ApprovalCards approvals={approvals} onAction={openAction} />
            </Card>
          </Grid>

          {pauses.length ? (
            <Card className="large-card section-grid danger-card">
              <Flex align="center" gap="2" mb="3">
                <ExclamationTriangleIcon />
                <Heading size="4">Assignment / expiration holds</Heading>
              </Flex>
              <Flex direction="column" gap="3">
                {pauses.map((pause) => (
                  <Flex key={pause.symbol} justify="between" align="center" gap="3" wrap="wrap">
                    <Box>
                      <Text weight="bold">{pause.symbol}</Text>
                      <Text as="div" size="2" color="gray">{pause.reason}</Text>
                    </Box>
                    <Button variant="soft" color="amber" onClick={() => acknowledgePause(pause.symbol)}>
                      Acknowledge
                    </Button>
                  </Flex>
                ))}
              </Flex>
            </Card>
          ) : null}

          <Card className="large-card section-grid">
            <Flex justify="between" align="center" mb="4">
              <Box>
                <Heading size="4">Recent Activity</Heading>
                <Text size="2" color="gray">Immutable-style application audit trail</Text>
              </Box>
              <Button variant="ghost" onClick={() => setSection("activity")}>
                View all <ChevronRightIcon />
              </Button>
            </Flex>
            <ActivityTable activity={activity.slice(0, 6)} />
          </Card>
        </>
      );
    }

    if (section === "opportunities") {
      return (
        <Flex direction="column" gap="4">
          <Card className="large-card">
            <Flex justify="between" align="end" gap="4" wrap="wrap">
              <Box>
                <Heading size="4">Read-only Option Scanner</Heading>
                <Text size="2" color="gray">
                  Loads live Robinhood chains, contracts, quotes, IV, and Greeks when available.
                </Text>
              </Box>
              <Flex gap="2" align="center">
                <TextField.Root
                  value={scanSymbol}
                  onChange={(e) => setScanSymbol(e.target.value.toUpperCase())}
                  placeholder="SPY"
                  style={{ width: 140 }}
                />
                <Button onClick={scanOptions} disabled={scanning || summary?.robinhood_connection_state !== "connected"}>
                  {scanning ? <ReloadIcon className="spin" /> : <LightningBoltIcon />}
                  {scanning ? "Scanning" : "Scan"}
                </Button>
              </Flex>
            </Flex>

            {summary?.robinhood_connection_state !== "connected" ? (
              <Callout.Root color="amber" mt="4">
                <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
                <Callout.Text>
                  Robinhood read sync must be connected before market-data scans can run.
                </Callout.Text>
              </Callout.Root>
            ) : null}
          </Card>

          {scanResult ? (
            <>
              <Grid columns={{ initial: "2", md: "4" }} gap="3">
                <Box className="position-stat">
                  <Text size="1" color="gray">Symbol</Text>
                  <Heading size="5">{scanResult.symbol}</Heading>
                </Box>
                <Box className="position-stat">
                  <Text size="1" color="gray">Chains</Text>
                  <Heading size="5">{scanResult.chain_count}</Heading>
                </Box>
                <Box className="position-stat">
                  <Text size="1" color="gray">Contracts</Text>
                  <Heading size="5">{scanResult.instrument_count}</Heading>
                </Box>
                <Box className="position-stat">
                  <Text size="1" color="gray">Quotes</Text>
                  <Heading size="5">{scanResult.quote_count}</Heading>
                </Box>
              </Grid>

              {Object.keys(scanResult.tool_errors || {}).length ? (
                <Callout.Root color="amber">
                  <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
                  <Callout.Text>
                    Some Robinhood read tools could not be called with the current advertised schema. See Settings/tool schemas for details.
                  </Callout.Text>
                </Callout.Root>
              ) : null}

              <Card className="large-card">
                <Flex justify="between" align="center" mb="4" gap="3" wrap="wrap">
                  <Box>
                    <Heading size="4">Phase 1 Candidates</Heading>
                    <Text size="2" color="gray">
                      Mechanical covered-call/CSP screening only. Candidates are not approval-ready trades.
                    </Text>
                  </Box>
                  <Flex gap="2" wrap="wrap">
                    {candidateResult ? (
                      <>
                        <Badge color="green" variant="soft">{candidateResult.passed_contracts} passed</Badge>
                        <Badge color="gray" variant="soft">{candidateResult.rejected_contracts} filtered</Badge>
                      </>
                    ) : null}
                    <Badge
                      color={candidateResult?.approval_ready ? "green" : "amber"}
                      variant="soft"
                    >
                      {candidateResult?.approval_ready
                        ? "DRY-RUN PROMOTION READY"
                        : "PORTFOLIO RISK PENDING"}
                    </Badge>
                  </Flex>
                </Flex>

                {candidateResult?.candidates?.length ? (
                  <div className="table-scroll">
                    <Table.Root variant="surface">
                      <Table.Header>
                        <Table.Row>
                          <Table.ColumnHeaderCell>Strategy</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Expiry</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>DTE</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Strike</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Delta</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Spread</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>OI</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Volume</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Credit</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Collateral</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Score</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Status</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Action</Table.ColumnHeaderCell>
                        </Table.Row>
                      </Table.Header>
                      <Table.Body>
                        {candidateResult.candidates.map((row, index) => (
                          <Table.Row key={(row.option_id || row.strategy) + index}>
                            <Table.Cell>
                              <Badge variant="soft" color={row.strategy === "covered_call" ? "green" : "blue"}>
                                {row.strategy.replaceAll("_", " ")}
                              </Badge>
                            </Table.Cell>
                            <Table.Cell>{row.expiration_date || "—"}</Table.Cell>
                            <Table.Cell>{row.dte ?? "—"}</Table.Cell>
                            <Table.Cell>{row.strike_price ? money(Number(row.strike_price)) : "—"}</Table.Cell>
                            <Table.Cell>{row.delta ?? "—"}</Table.Cell>
                            <Table.Cell>{row.spread_pct == null ? "—" : pct(row.spread_pct)}</Table.Cell>
                            <Table.Cell>{row.open_interest ?? "—"}</Table.Cell>
                            <Table.Cell>{row.volume ?? "—"}</Table.Cell>
                            <Table.Cell>{row.estimated_credit ? money(Number(row.estimated_credit)) : "—"}</Table.Cell>
                            <Table.Cell>{row.estimated_collateral ? money(Number(row.estimated_collateral)) : "—"}</Table.Cell>
                            <Table.Cell>{row.score.toFixed(1)}</Table.Cell>
                            <Table.Cell>
                              <Badge color={row.risk_status === "buying_power_reject" ? "red" : "amber"} variant="soft">
                                {row.risk_status.replaceAll("_", " ")}
                              </Badge>
                            </Table.Cell>
                            <Table.Cell>
                              {row.strategy === "cash_secured_put" ? (
                                <Button
                                  size="1"
                                  variant={candidateResult?.approval_ready ? "solid" : "soft"}
                                  disabled={
                                    !candidateResult?.approval_ready ||
                                    row.buying_power_sufficient !== true ||
                                    promotingId === row.option_id
                                  }
                                  onClick={() => promoteCandidate(row)}
                                >
                                  {promotingId === row.option_id ? (
                                    <ReloadIcon className="spin" />
                                  ) : (
                                    <CheckCircledIcon />
                                  )}
                                  Promote
                                </Button>
                              ) : (
                                <Tooltip content="Covered-call promotion remains locked until whole-position stock risk is authoritative.">
                                  <Badge color="gray" variant="soft">Locked</Badge>
                                </Tooltip>
                              )}
                            </Table.Cell>
                          </Table.Row>
                        ))}
                      </Table.Body>
                    </Table.Root>
                  </div>
                ) : (
                  <EmptyPanel
                    icon={MixerHorizontalIcon}
                    title="No Phase 1 candidates passed"
                    body="No covered-call or CSP contracts met the configured DTE, liquidity, delta, coverage, and collateral filters."
                  />
                )}

                {candidateResult ? (
                  <Callout.Root color={candidateResult.approval_ready ? "green" : "amber"} mt="4">
                    <Callout.Icon>
                      {candidateResult.approval_ready ? <CheckCircledIcon /> : <LockClosedIcon />}
                    </Callout.Icon>
                    <Callout.Text>
                      {candidateResult.note}
                      {!candidateResult.approval_ready && candidateResult.risk_state_reasons?.length
                        ? " " + candidateResult.risk_state_reasons.join(" · ")
                        : ""}
                    </Callout.Text>
                  </Callout.Root>
                ) : null}
                {candidateResult?.diagnostics?.some((item) => !item.passed) ? (
                  <Box mt="4">
                    <Text size="2" weight="bold">Filter diagnostics</Text>
                    <Flex direction="column" gap="2" mt="2">
                      {candidateResult.diagnostics
                        .filter((item) => !item.passed)
                        .slice(0, 12)
                        .map((item, index) => (
                          <Flex key={(item.option_id || "diag") + index} gap="2" align="start">
                            <Badge color="gray" variant="soft">
                              {(item.option_type || "option") + " " + (item.strike_price || "—")}
                            </Badge>
                            <Text size="1" color="gray">
                              {item.reasons.join(" · ")}
                            </Text>
                          </Flex>
                        ))}
                    </Flex>
                  </Box>
                ) : null}

              </Card>

              <Card className="large-card">
                <Flex justify="between" align="center" mb="4">
                  <Box>
                    <Heading size="4">Option Contracts</Heading>
                    <Text size="2" color="gray">
                      Sorted by quoted bid/ask spread only. No trade recommendation is being made.
                    </Text>
                  </Box>
                  <Badge color="green" variant="soft">READ ONLY</Badge>
                </Flex>

                {scanResult.contracts?.length ? (
                  <div className="table-scroll">
                    <Table.Root variant="surface">
                      <Table.Header>
                        <Table.Row>
                          <Table.ColumnHeaderCell>Expiry</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Type</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Strike</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Bid</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Ask</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Spread</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>IV</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Delta</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Theta</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>OI</Table.ColumnHeaderCell>
                          <Table.ColumnHeaderCell>Volume</Table.ColumnHeaderCell>
                        </Table.Row>
                      </Table.Header>
                      <Table.Body>
                        {scanResult.contracts.slice(0, 100).map((row, index) => (
                          <Table.Row key={(row.option_id || "contract") + index}>
                            <Table.Cell>{row.expiration_date || "—"}</Table.Cell>
                            <Table.Cell>{row.option_type || "—"}</Table.Cell>
                            <Table.Cell>{row.strike_price || "—"}</Table.Cell>
                            <Table.Cell>{row.bid == null ? "—" : money(row.bid)}</Table.Cell>
                            <Table.Cell>{row.ask == null ? "—" : money(row.ask)}</Table.Cell>
                            <Table.Cell>{row.spread_pct == null ? "—" : pct(row.spread_pct)}</Table.Cell>
                            <Table.Cell>{row.implied_volatility == null ? "—" : pct(row.implied_volatility * (row.implied_volatility <= 5 ? 100 : 1))}</Table.Cell>
                            <Table.Cell>{row.delta ?? "—"}</Table.Cell>
                            <Table.Cell>{row.theta ?? "—"}</Table.Cell>
                            <Table.Cell>{row.open_interest ?? "—"}</Table.Cell>
                            <Table.Cell>{row.volume ?? "—"}</Table.Cell>
                          </Table.Row>
                        ))}
                      </Table.Body>
                    </Table.Root>
                  </div>
                ) : (
                  <EmptyPanel
                    icon={LightningBoltIcon}
                    title="No option contracts returned"
                    body="The live Robinhood schemas may require a field TradeHub could not safely infer, or the symbol has no returned contracts."
                  />
                )}
              </Card>
            </>
          ) : (
            <Card className="large-card">
              <EmptyPanel
                icon={LightningBoltIcon}
                title="Scan a symbol"
                body="Enter an underlying symbol to inspect Robinhood option-chain data. This scanner is informational and cannot submit orders."
              />
            </Card>
          )}
        </Flex>
      );
    }

    if (section === "approvals") {
      return (
        <Card className="large-card">
          <Flex justify="between" align="center" mb="4">
            <Heading size="4">Approval Queue</Heading>
            <Badge color={approvals.length ? "amber" : "green"}>{approvals.length} pending</Badge>
          </Flex>
          <ApprovalCards approvals={approvals} onAction={openAction} />
        </Card>
      );
    }

    if (section === "risk") {
      return (
        <Grid columns={{ initial: "1", lg: "2" }} gap="4">
          <RiskPanel summary={summary} />
          <Card className="large-card">
            <Heading size="4">Execution safeguards</Heading>
            <Flex direction="column" gap="3" mt="4">
              {[
                ["Defined-risk only", "Naked option selling is rejected before execution."],
                ["Portfolio cap", "Aggregate known max-loss cannot exceed the configured limit."],
                ["Daily circuit breaker", "New entries halt when realized losses reach the threshold."],
                ["Assignment hold", "TradeHub pauses the underlying and requires manual acknowledgement."]
              ].map(([name, body]) => (
                <Flex key={name} gap="3" align="start">
                  <CheckCircledIcon className="positive" width="18" height="18" />
                  <Box>
                    <Text weight="bold">{name}</Text>
                    <Text as="div" size="2" color="gray">{body}</Text>
                  </Box>
                </Flex>
              ))}
            </Flex>
          </Card>
        </Grid>
      );
    }

    if (section === "activity") {
      return <Card className="large-card"><ActivityTable activity={activity} /></Card>;
    }

    if (section === "settings") {
      return (
        <Grid columns={{ initial: "1", lg: "2" }} gap="4">
          <Card className="large-card">
            <Heading size="4">Robinhood Agentic</Heading>
            <Flex direction="column" gap="3" mt="4">
              <Flex justify="between"><Text color="gray">MCP endpoint</Text><Text>agent.robinhood.com</Text></Flex>
              <Separator size="4" />
              <Flex justify="between"><Text color="gray">MCP enabled</Text><Badge color={summary?.robinhood_mcp_enabled ? "green" : "gray"}>{summary?.robinhood_mcp_enabled ? "Yes" : "No"}</Badge></Flex>
              <Flex justify="between"><Text color="gray">Connection</Text><Badge color={summary?.robinhood_connection_state === "connected" ? "green" : "amber"}>{summary?.robinhood_connection_state || "disabled"}</Badge></Flex>
              <Flex justify="between"><Text color="gray">Last sync</Text><Text>{formatDate(summary?.robinhood_last_sync)}</Text></Flex>
              <Flex justify="between"><Text color="gray">Trading mode</Text><Badge color={summary?.trading_mode === "live" ? "red" : "amber"}>{summary?.trading_mode === "live" ? "LIVE" : "DRY RUN"}</Badge></Flex>
              <Flex justify="between"><Text color="gray">Rollout phase</Text><Text>{summary?.phase ?? 0}</Text></Flex>
              <Flex justify="between"><Text color="gray">Approval required</Text><Text>{summary?.require_approval ? "Yes" : "No"}</Text></Flex>
              {summary?.robinhood_last_error ? <Callout.Root color="amber"><Callout.Text>{summary.robinhood_last_error}</Callout.Text></Callout.Root> : null}
            </Flex>
          </Card>
          <Card className="large-card">
            <Heading size="4">Notifications</Heading>
            <Text as="div" size="2" color="gray" mt="2">
              Browser notifications can alert you when a new approval arrives while this dashboard is open.
            </Text>
            <Button mt="4" variant="soft" onClick={enableNotifications}>
              <BellIcon /> Enable browser notifications
            </Button>
          </Card>
        </Grid>
      );
    }

    if (section === "strategy") {
      return (
        <Grid columns={{ initial: "1", lg: "3" }} gap="4">
          <Card className="large-card">
            <Badge color="green" mb="3">Phase 0</Badge>
            <Heading size="4">Dry Run</Heading>
            <Text as="div" color="gray" size="2" mt="2">Full decision pipeline, logging, approvals, and no broker writes.</Text>
          </Card>
          <Card className="large-card">
            <Badge color="amber" mb="3">Phase 1</Badge>
            <Heading size="4">Single-leg Live</Heading>
            <Text as="div" color="gray" size="2" mt="2">Cash-secured puts and covered calls. One concurrent position initially.</Text>
          </Card>
          <Card className="large-card">
            <Badge color="gray" mb="3">Phase 2</Badge>
            <Heading size="4">Defined-risk Spreads</Heading>
            <Text as="div" color="gray" size="2" mt="2">Verticals, debit spreads, long options, and iron condors with leg sequencing.</Text>
          </Card>
        </Grid>
      );
    }

    if (section === "positions") {
      const hasPositions = positions.equities.length || positions.options.length;
      if (!hasPositions) {
        return (
          <Card className="large-card">
            <EmptyPanel
              icon={BackpackIcon}
              title="No synchronized positions"
              body={
                summary?.robinhood_connection_state === "connected"
                  ? "Robinhood is connected and no open stock or option positions were returned."
                  : "Authenticate Robinhood MCP to populate live stock and option positions."
              }
            />
          </Card>
        );
      }

      return (
        <Flex direction="column" gap="4">
          <Card className="large-card">
            <Flex justify="between" align="center" mb="4">
              <Box>
                <Heading size="4">Equity Positions</Heading>
                <Text size="2" color="gray">Robinhood holdings synced read-only</Text>
              </Box>
              <Badge variant="soft">{positions.equities.length} open</Badge>
            </Flex>
            {positions.equities.length ? (
              <div className="table-scroll">
                <Table.Root variant="surface">
                  <Table.Header>
                    <Table.Row>
                      <Table.ColumnHeaderCell>Symbol</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Direction</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Quantity</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Avg. Buy Price</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Available</Table.ColumnHeaderCell>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {positions.equities.map((row, index) => (
                      <Table.Row key={(row.symbol || "equity") + index}>
                        <Table.Cell><Text weight="bold">{row.symbol || "—"}</Text></Table.Cell>
                        <Table.Cell>{row.direction || "long"}</Table.Cell>
                        <Table.Cell>{row.quantity ?? "—"}</Table.Cell>
                        <Table.Cell>{row.average_buy_price ? money(Number(row.average_buy_price)) : "—"}</Table.Cell>
                        <Table.Cell>{row.shares_available_for_sells ?? "—"}</Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table.Root>
              </div>
            ) : (
              <Text color="gray" size="2">No equity positions.</Text>
            )}
          </Card>

          <Card className="large-card">
            <Flex justify="between" align="center" mb="4">
              <Box>
                <Heading size="4">Option Positions</Heading>
                <Text size="2" color="gray">Open Robinhood option contracts</Text>
              </Box>
              <Badge variant="soft">{positions.options.length} open</Badge>
            </Flex>
            {positions.options.length ? (
              <div className="table-scroll">
                <Table.Root variant="surface">
                  <Table.Header>
                    <Table.Row>
                      <Table.ColumnHeaderCell>Symbol</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Direction</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Quantity</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Average Price</Table.ColumnHeaderCell>
                      <Table.ColumnHeaderCell>Expiration</Table.ColumnHeaderCell>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {positions.options.map((row, index) => (
                      <Table.Row key={(row.option_id || row.symbol || "option") + index}>
                        <Table.Cell><Text weight="bold">{row.symbol || "—"}</Text></Table.Cell>
                        <Table.Cell>{row.direction || "—"}</Table.Cell>
                        <Table.Cell>{row.quantity ?? "—"}</Table.Cell>
                        <Table.Cell>{row.average_price ? money(Number(row.average_price)) : "—"}</Table.Cell>
                        <Table.Cell>{row.expiration_date || "—"}</Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table.Root>
              </div>
            ) : (
              <Text color="gray" size="2">No option positions.</Text>
            )}
          </Card>
        </Flex>
      );
    }

    return (
      <Card className="large-card">
        <EmptyPanel
          icon={LightningBoltIcon}
          title="Strategy scanner not active yet"
          body="This workspace is reserved for ranked option candidates based on IV rank, direction, liquidity, holdings, and configured risk."
        />
      </Card>
    );
  }

  return (
    <Theme appearance="dark" accentColor="green" grayColor="slate" panelBackground="solid" radius="large" scaling="100%">
      <div className="app-shell">
        <Sidebar section={section} setSection={setSection} approvalCount={approvals.length} />

        <div className="workspace">
          <header className="topbar">
            <StatusPill summary={summary} />
            <Flex align="center" gap="2">
              <Tooltip content="Refresh dashboard">
                <IconButton variant="ghost" color="gray" onClick={() => refresh(false)}>
                  <ReloadIcon />
                </IconButton>
              </Tooltip>
              <Tooltip content="Enable approval notifications">
                <IconButton variant="ghost" color="gray" onClick={enableNotifications}>
                  <BellIcon />
                </IconButton>
              </Tooltip>
              <div className="avatar">SM</div>
            </Flex>
          </header>

          <main className="content">
            <Flex justify="between" align="end" gap="4" wrap="wrap" mb="5">
              <Box>
                <Heading size="7">{title}</Heading>
                <Text color="gray" size="3">{subtitle}</Text>
              </Box>
              <Badge color="green" variant="soft">
                <DotFilledIcon /> Robinhood-only
              </Badge>
            </Flex>

            {error ? (
              <Callout.Root color="red" mb="4">
                <Callout.Icon><ExclamationTriangleIcon /></Callout.Icon>
                <Callout.Text>{error}</Callout.Text>
              </Callout.Root>
            ) : null}

            {loading && !summary ? (
              <Card className="large-card">
                <Flex align="center" gap="3">
                  <ReloadIcon className="spin" />
                  <Text>Loading TradeHub...</Text>
                </Flex>
              </Card>
            ) : renderMain()}
          </main>
        </div>
      </div>

      <ActionDialog state={dialog} setState={setDialog} onSubmit={submitAction} />
    </Theme>
  );
}
