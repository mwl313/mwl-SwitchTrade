using System.Collections;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace SwitchTrade.Desktop.Views.Components;

public partial class PartyGrid : UserControl
{
    public static readonly DependencyProperty HeadingProperty =
        DependencyProperty.Register(nameof(Heading), typeof(string), typeof(PartyGrid));
    public static readonly DependencyProperty SlotsProperty =
        DependencyProperty.Register(nameof(Slots), typeof(IEnumerable), typeof(PartyGrid));
    public static readonly DependencyProperty SelectCommandProperty =
        DependencyProperty.Register(nameof(SelectCommand), typeof(ICommand), typeof(PartyGrid));
    public static readonly DependencyProperty AccentBrushProperty =
        DependencyProperty.Register(nameof(AccentBrush), typeof(Brush), typeof(PartyGrid));

    public PartyGrid() => InitializeComponent();
    public string Heading { get => (string)GetValue(HeadingProperty); set => SetValue(HeadingProperty, value); }
    public IEnumerable Slots { get => (IEnumerable)GetValue(SlotsProperty); set => SetValue(SlotsProperty, value); }
    public ICommand SelectCommand { get => (ICommand)GetValue(SelectCommandProperty); set => SetValue(SelectCommandProperty, value); }
    public Brush AccentBrush { get => (Brush)GetValue(AccentBrushProperty); set => SetValue(AccentBrushProperty, value); }
}
