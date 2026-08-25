using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace SwitchTrade.Desktop.Controls;

public sealed class ScenePresenter : ContentControl
{
    protected override void OnContentChanged(object oldContent, object newContent)
    {
        base.OnContentChanged(oldContent, newContent);
        if (!SystemParameters.ClientAreaAnimation || SystemParameters.HighContrast)
        {
            Opacity = 1;
            RenderTransform = Transform.Identity;
            return;
        }

        var transform = new TranslateTransform(8, 0);
        RenderTransform = transform;
        Opacity = 0;
        BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(160))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
        });
        transform.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(8, 0, TimeSpan.FromMilliseconds(160))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
        });
    }
}
