using System.Windows;
using System.Windows.Controls;

namespace SwitchTrade.Desktop.Views.Components;

public partial class LinklineControl : UserControl
{
    public static readonly DependencyProperty YouSummaryProperty =
        DependencyProperty.Register(nameof(YouSummary), typeof(string), typeof(LinklineControl));
    public static readonly DependencyProperty PartnerSummaryProperty =
        DependencyProperty.Register(nameof(PartnerSummary), typeof(string), typeof(LinklineControl));
    public static readonly DependencyProperty YouPresenceProperty =
        DependencyProperty.Register(nameof(YouPresence), typeof(string), typeof(LinklineControl));
    public static readonly DependencyProperty PartnerPresenceProperty =
        DependencyProperty.Register(nameof(PartnerPresence), typeof(string), typeof(LinklineControl));
    public static readonly DependencyProperty PartnerIsOnlineProperty =
        DependencyProperty.Register(nameof(PartnerIsOnline), typeof(bool), typeof(LinklineControl));
    public static readonly DependencyProperty StatusTextProperty =
        DependencyProperty.Register(nameof(StatusText), typeof(string), typeof(LinklineControl));

    public LinklineControl() => InitializeComponent();
    public string YouSummary { get => (string)GetValue(YouSummaryProperty); set => SetValue(YouSummaryProperty, value); }
    public string PartnerSummary { get => (string)GetValue(PartnerSummaryProperty); set => SetValue(PartnerSummaryProperty, value); }
    public string YouPresence { get => (string)GetValue(YouPresenceProperty); set => SetValue(YouPresenceProperty, value); }
    public string PartnerPresence { get => (string)GetValue(PartnerPresenceProperty); set => SetValue(PartnerPresenceProperty, value); }
    public bool PartnerIsOnline { get => (bool)GetValue(PartnerIsOnlineProperty); set => SetValue(PartnerIsOnlineProperty, value); }
    public string StatusText { get => (string)GetValue(StatusTextProperty); set => SetValue(StatusTextProperty, value); }
}
