import { Component, type ErrorInfo, type ReactNode } from "react";

type DashboardErrorBoundaryProps = {
  children: ReactNode;
  resetKey?: string;
};

type DashboardErrorBoundaryState = {
  error: Error | null;
};

export class DashboardErrorBoundary extends Component<
  DashboardErrorBoundaryProps,
  DashboardErrorBoundaryState
> {
  state: DashboardErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): DashboardErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard section failed", error, info);
  }

  componentDidUpdate(previousProps: DashboardErrorBoundaryProps) {
    if (this.state.error && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="alert alert-error text-sm" role="alert">
          <div>
            <div className="font-semibold">Dashboard section failed</div>
            <div className="mt-1 opacity-80">{this.state.error.message}</div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
