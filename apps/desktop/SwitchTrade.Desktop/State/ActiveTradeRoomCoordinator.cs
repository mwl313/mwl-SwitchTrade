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
    public string? RecoveryCode { get; private set; }
    public string? RecoveryStage { get; private set; }
    public bool RecoveryRecoverable { get; private set; }
    public string? RecoveryAction { get; private set; }
    public string RoomState { get; private set; } = "waiting_for_partner";
    public string AttemptPhase { get; private set; } = "none";
    public bool PartnerOnline { get; private set; }
    public string LocalTrainerDisplayName { get; private set; } = "Trainer";
    public string PartnerTrainerDisplayName { get; private set; } = "";
    public bool BothReady { get; private set; }
    public bool RoleLocked { get; private set; }
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
        ClearRecovery();
        RoomState = room.Participants >= 2 ? "ready_check" : "waiting_for_partner";
        AttemptPhase = "none";
        PartnerOnline = room.Participants >= 2;
        LocalTrainerDisplayName = string.IsNullOrWhiteSpace(room.LocalTrainerDisplayName)
            ? membershipRole == RoomMembershipRole.Owner && !string.IsNullOrWhiteSpace(room.TrainerDisplayName)
                ? room.TrainerDisplayName : "Trainer"
            : room.LocalTrainerDisplayName;
        PartnerTrainerDisplayName = string.IsNullOrWhiteSpace(room.PartnerTrainerDisplayName)
            ? membershipRole == RoomMembershipRole.Member ? room.TrainerDisplayName : ""
            : room.PartnerTrainerDisplayName;
        BothReady = false;
        RoleLocked = false;
        RaiseChanged();
    }

    public async Task<bool> StartConnectionAsync(
        SwitchRoomRole switchRole, CancellationToken cancellationToken = default)
    {
        if (Context is null || IsPending || switchRole == SwitchRoomRole.Unassigned) return false;
        Context = Context with { SwitchRole = switchRole };
        ConnectionState = LegacyConnectionState.Starting;
        StatusText = switchRole == SwitchRoomRole.Creator
            ? "Looking for the group on your Switch"
            : "Preparing your partner’s group";
        ClearRecovery();
        RaiseChanged();
        try
        {
            await _gateway.StartConnectionAsync(
                switchRole, Context.MembershipRole, Context.Room.RoomCode, cancellationToken);
            StatusText = "Preparing the connection. Follow the Switch instructions.";
            RaiseChanged();
            return true;
        }
        catch (UserFacingException error)
        {
            ConnectionState = LegacyConnectionState.NeedsRecovery;
            StatusText = error.UserMessage;
            RecoveryMessage = error.UserMessage;
            RecoveryCode = error.TechnicalCode;
            RecoveryStage = error.Stage;
            RecoveryRecoverable = error.Recoverable;
            RecoveryAction = error.PrimaryAction;
            RaiseChanged();
            return false;
        }
    }

    public async Task<bool> StopConnectionAsync(CancellationToken cancellationToken = default)
    {
        if (Context is null || ConnectionState == LegacyConnectionState.Idle) return true;
        ConnectionState = LegacyConnectionState.Ending;
        StatusText = "Ending the connection…";
        ClearRecovery();
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
            RecoveryCode = error.TechnicalCode;
            RecoveryStage = error.Stage;
            RecoveryRecoverable = error.Recoverable;
            RecoveryAction = error.PrimaryAction;
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
        ClearRecovery();
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
            RecoveryCode = error.TechnicalCode;
            RecoveryStage = error.Stage;
            RecoveryRecoverable = error.Recoverable;
            RecoveryAction = error.PrimaryAction;
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
                StatusText = Context.SwitchRole == SwitchRoomRole.Creator
                    ? "Looking for the group on your Switch"
                    : "Preparing your partner’s group";
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
                RecoveryCode = status.FailureCode;
                RecoveryMessage = status.FailureCode switch
                {
                    "radio.switch_room_not_found" =>
                        "No Group Leader Switch room was found on supported 2.4 GHz channels. Recreate the group on the Switch and try again.",
                    _ => status.FailureStage switch
                    {
                        "relay" => "Check this PC’s internet connection, end this attempt, and try again. Export a support bundle if it repeats.",
                        "radio" => "Run the adapter check. End this attempt before reattaching USB or starting another room.",
                        "session" => "End this attempt and try once more. Export a support bundle if the same session failure repeats.",
                        "cleanup" => "Restart SwitchTrade before trying another connection. Export a support bundle if it repeats.",
                        "decoder" => "End this attempt and repair or update SwitchTrade; the installed decoder does not match this app.",
                        "control" => "Close SwitchTrade and run the latest SwitchTradeSetup.exe with Repair. Do not reset WSL.",
                        _ => status.Error ?? "End this attempt and try again. Export a support bundle if it repeats.",
                    },
                };
                break;
            case "completed":
                ConnectionState = LegacyConnectionState.Idle;
                StatusText = "Connection ended. This Trade Room is still open.";
                ClearRecovery();
                break;
            default:
                return;
        }
        RaiseChanged();
    }

    public void ApplyRoom(AuthoritativeRoomProjection room)
    {
        if (Context is null) return;
        if (room.State is "closed" or "expired")
        {
            ForceClear();
            return;
        }
        Context = Context with
        {
            MembershipRole = room.MembershipRole,
            SwitchRole = room.SwitchRole,
            Room = Context.Room with
            {
                Participants = room.Participants,
                LocalTrainerDisplayName = string.IsNullOrWhiteSpace(room.LocalTrainerDisplayName)
                    ? Context.Room.LocalTrainerDisplayName : room.LocalTrainerDisplayName,
                PartnerTrainerDisplayName = string.IsNullOrWhiteSpace(room.PartnerTrainerDisplayName)
                    ? Context.Room.PartnerTrainerDisplayName : room.PartnerTrainerDisplayName,
            },
        };
        RoomState = room.State;
        AttemptPhase = room.AttemptPhase;
        PartnerOnline = room.PartnerOnline;
        if (!string.IsNullOrWhiteSpace(room.LocalTrainerDisplayName))
            LocalTrainerDisplayName = room.LocalTrainerDisplayName;
        if (!string.IsNullOrWhiteSpace(room.PartnerTrainerDisplayName))
            PartnerTrainerDisplayName = room.PartnerTrainerDisplayName;
        BothReady = room.BothReady;
        RoleLocked = room.RoleLocked;
        if (room.AttemptPhase == "failed")
        {
            ConnectionState = LegacyConnectionState.NeedsRecovery;
            StatusText = "This connection needs attention.";
            RecoveryCode = room.FailureCode ?? "session.failed";
            RecoveryStage = room.FailureStage ?? "session";
            RecoveryRecoverable = room.FailureRecoverable;
            RecoveryAction = room.FailureAction ?? "retry";
            RecoveryMessage = RecoveryCode switch
            {
                "relay.restart" => "The online relay restarted. End this attempt and try again.",
                "relay.peer_lost" => "The partner connection was lost. End this attempt and try again.",
                "member.reconnect_expired" => "Your partner did not reconnect in time.",
                "radio.switch_room_not_found" =>
                    "No Group Leader Switch room was found on supported 2.4 GHz channels. Recreate the group on the Switch and try again.",
                _ => "End this attempt and try again. Export a support bundle if it repeats.",
            };
        }
        else if (ConnectionState == LegacyConnectionState.Idle && room.RoleLocked)
        {
            ConnectionState = room.State == "trading"
                ? LegacyConnectionState.Active
                : LegacyConnectionState.Starting;
        }
        if (ConnectionState == LegacyConnectionState.Idle)
        {
            StatusText = room.State switch
            {
                "waiting_for_partner" => "Waiting for your partner",
                "ready_check" when !room.BothReady => "Both trainers are here. Choose what your Switch is doing.",
                "ready_check" => "Both trainers chose their Switch roles",
                "connection_attempt" when !room.RoleLocked => "Waiting for opposite Switch roles",
                "connection_attempt" => "Preparing both Switch connections",
                "trading" => "Both Switches are in the trading room",
                "closed" => "This Trade Room is closed",
                _ => room.PartnerOnline ? "Both trainers are in this Trade Room" : "Waiting for your partner",
            };
        }
        RaiseChanged();
    }

    public void ForceClear()
    {
        Context = null;
        ConnectionState = LegacyConnectionState.Idle;
        StatusText = "Connection not started";
        ClearRecovery();
        RoomState = "waiting_for_partner";
        AttemptPhase = "none";
        PartnerOnline = false;
        LocalTrainerDisplayName = "Trainer";
        PartnerTrainerDisplayName = "";
        BothReady = false;
        RoleLocked = false;
        RaiseChanged();
    }

    private void RaiseChanged() => Changed?.Invoke(this, EventArgs.Empty);

    private void ClearRecovery()
    {
        RecoveryMessage = null;
        RecoveryCode = null;
        RecoveryStage = null;
        RecoveryRecoverable = false;
        RecoveryAction = null;
    }
}
