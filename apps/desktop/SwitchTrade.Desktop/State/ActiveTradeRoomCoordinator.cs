using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.State;

public enum LegacyConnectionState
{
    Idle,
    Starting,
    Active,
    Ending,
    ClosingRoom,
    NeedsRecovery,
}

public sealed record ActiveTradeRoomContext(
    TradeRoomInfo Room,
    RoomMembershipRole MembershipRole,
    SwitchRoomRole SwitchRole,
    TradeRoomCreateRequest? LocalInvitation);

public sealed class ActiveTradeRoomCoordinator(IControlGateway gateway)
{
    private readonly IControlGateway _gateway = gateway;

    public event EventHandler? Changed;

    public ActiveTradeRoomContext? Context { get; private set; }
    public LegacyConnectionState ConnectionState { get; private set; } = LegacyConnectionState.Idle;
    public string StatusText { get; private set; } = "Connection not started";
    public string? RecoveryMessage { get; private set; }
    public bool HasRoom => Context is not null;
    public bool HasConnectionOrUncertainTeardown =>
        ConnectionState is not LegacyConnectionState.Idle;
    public bool IsPending => ConnectionState is LegacyConnectionState.Starting
        or LegacyConnectionState.Ending or LegacyConnectionState.ClosingRoom;

    public void Open(
        TradeRoomInfo room,
        RoomMembershipRole membershipRole,
        SwitchRoomRole switchRole,
        TradeRoomCreateRequest? localInvitation = null)
    {
        Context = new(room, membershipRole, switchRole, localInvitation);
        ConnectionState = LegacyConnectionState.Idle;
        StatusText = "Connection not started";
        RecoveryMessage = null;
        RaiseChanged();
    }

    public async Task<bool> StartConnectionAsync(CancellationToken cancellationToken = default)
    {
        if (Context is null || IsPending) return false;
        ConnectionState = LegacyConnectionState.Starting;
        StatusText = "Preparing the connection";
        RecoveryMessage = null;
        RaiseChanged();
        try
        {
            await _gateway.StartConnectionAsync(
                Context.SwitchRole, Context.MembershipRole, Context.Room.RoomCode, cancellationToken);
            StatusText = "Preparing the connection. Follow the Switch instructions.";
            RaiseChanged();
            return true;
        }
        catch (UserFacingException error)
        {
            ConnectionState = LegacyConnectionState.NeedsRecovery;
            StatusText = error.UserMessage;
            RecoveryMessage = error.UserMessage;
            RaiseChanged();
            return false;
        }
    }

    public async Task<bool> StopConnectionAsync(CancellationToken cancellationToken = default)
    {
        if (Context is null || ConnectionState == LegacyConnectionState.Idle) return true;
        ConnectionState = LegacyConnectionState.Ending;
        StatusText = "Ending the connection…";
        RecoveryMessage = null;
        RaiseChanged();
        try
        {
            await _gateway.StopConnectionAsync(cancellationToken);
            ConnectionState = LegacyConnectionState.Idle;
            StatusText = "Connection ended. This Trade Room is still open.";
            RaiseChanged();
            return true;
        }
        catch (UserFacingException error)
        {
            ConnectionState = LegacyConnectionState.NeedsRecovery;
            StatusText = "SwitchTrade couldn’t confirm that the connection ended.";
            RecoveryMessage = error.UserMessage;
            RaiseChanged();
            return false;
        }
    }

    public async Task<bool> ReleaseRoomAsync(CancellationToken cancellationToken = default)
    {
        if (Context is null) return true;
        if (ConnectionState != LegacyConnectionState.Idle &&
            !await StopConnectionAsync(cancellationToken)) return false;

        var context = Context;
        ConnectionState = LegacyConnectionState.ClosingRoom;
        StatusText = context.MembershipRole == RoomMembershipRole.Owner
            ? "Closing this Trade Room…"
            : "Leaving this Trade Room…";
        RecoveryMessage = null;
        RaiseChanged();
        try
        {
            await _gateway.ReleaseTradeRoomAsync(
                context.Room.RoomCode, context.MembershipRole, cancellationToken);
            ForceClear();
            return true;
        }
        catch (UserFacingException error)
        {
            ConnectionState = LegacyConnectionState.NeedsRecovery;
            StatusText = context.MembershipRole == RoomMembershipRole.Owner
                ? "SwitchTrade couldn’t confirm that the Trade Room closed."
                : "SwitchTrade couldn’t confirm that you left the Trade Room.";
            RecoveryMessage = error.UserMessage;
            RaiseChanged();
            return false;
        }
    }

    public void ApplyStatus(ControlStatus status)
    {
        if (Context is null || ConnectionState is LegacyConnectionState.Idle or LegacyConnectionState.ClosingRoom)
            return;

        switch (status.Status)
        {
            case "initializing":
            case "starting":
                ConnectionState = LegacyConnectionState.Starting;
                StatusText = "Preparing the connection";
                break;
            case "relay_connected":
                ConnectionState = LegacyConnectionState.Starting;
                StatusText = "Waiting for the room on the creator’s Switch";
                break;
            case "radio_ready":
                ConnectionState = LegacyConnectionState.Starting;
                StatusText = "The local Switch connection is ready";
                break;
            case "session_ready":
                ConnectionState = LegacyConnectionState.Active;
                StatusText = "Both Switches are connected";
                break;
            case "failed":
                ConnectionState = LegacyConnectionState.NeedsRecovery;
                StatusText = "This connection needs attention.";
                RecoveryMessage = status.Error ?? "End the connection, check Settings, and try again.";
                break;
            case "completed":
                ConnectionState = LegacyConnectionState.Idle;
                StatusText = "Connection ended. This Trade Room is still open.";
                RecoveryMessage = null;
                break;
            default:
                return;
        }
        RaiseChanged();
    }

    public void ForceClear()
    {
        Context = null;
        ConnectionState = LegacyConnectionState.Idle;
        StatusText = "Connection not started";
        RecoveryMessage = null;
        RaiseChanged();
    }

    private void RaiseChanged() => Changed?.Invoke(this, EventArgs.Empty);
}
