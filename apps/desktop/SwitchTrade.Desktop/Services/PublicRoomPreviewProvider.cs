using SwitchTrade.Desktop.Models;

namespace SwitchTrade.Desktop.Services;

public sealed class PublicRoomPreviewProvider(Func<DateTimeOffset>? clock = null)
{
    private readonly Func<DateTimeOffset> _clock = clock ?? (() => DateTimeOffset.UtcNow);

    public IReadOnlyList<PublicRoomPreview> GetRooms()
    {
        var now = _clock();
        return
        [
            new("demo-1", "Kanto afternoon trades", "Leaf", GameVersionChoice.FireRed, GameLanguage.English,
                "Bulbasaur", "Any version exclusive", "East Asia", PreviewAvailability.Open, 42, now.AddMinutes(-6),
                "One relaxed trade before dinner."),
            new("demo-2", "Complete the Pokédex", "GreenTrainer", GameVersionChoice.LeafGreen, GameLanguage.English,
                "Pinsir", "Scyther", "North America", PreviewAvailability.Open, 88, now.AddMinutes(-18),
                "Version-exclusive swaps welcome."),
            new("demo-3", "Late-night link club", "MAY", GameVersionChoice.FireRed, GameLanguage.Japanese,
                "Dratini", "Starter Pokémon", "East Asia", PreviewAvailability.Open, 61, now.AddMinutes(-29),
                "日本語 / English is okay."),
            new("demo-4", "Berry and item trades", "Nora", GameVersionChoice.LeafGreen, GameLanguage.French,
                "Chansey", "Anything", "Europe", PreviewAvailability.Open, 117, now.AddMinutes(-44),
                "Held-item trades are fine."),
            new("demo-5", "Quick version swap", "Red", GameVersionChoice.FireRed, GameLanguage.English,
                "Growlithe", "Vulpix", "Oceania", PreviewAvailability.Full, 154, now.AddHours(-1),
                "Room currently has two trainers."),
        ];
    }

    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "Party fixtures remain behind the injected preview-provider boundary.")]
    public (PartyPreviewViewData You, PartyPreviewViewData Partner) GetSampleParties()
    {
        var empty = new PokemonPreviewViewData("", "", 0, "", null, null, null, null, [], null, true);
        var you = new PartyPreviewViewData("You", "Blue",
        [
            Pokemon("BULBY", "Bulbasaur", 18, "Calm", "Oran Berry",
                new(49, 25, 27, 33, 38, 24), new(20, 14, 19, 25, 28, 17), new(12, 0, 8, 20, 16, 0),
                ["Vine Whip", "Sleep Powder", "Leech Seed", "Tackle"], "SAMPLE"),
            Pokemon("RATTA", "Rattata", 12, "Jolly", null,
                new(32, 23, 15, 12, 16, 29), new(18, 24, 13, 8, 17, 27), new(0, 12, 0, 0, 0, 18),
                ["Quick Attack", "Tail Whip", "Hyper Fang", "Focus Energy"], "SAMPLE"),
            empty, empty, empty, empty,
        ]);
        var partner = new PartyPreviewViewData("Partner", "Teal",
        [
            Pokemon("SHELLY", "Squirtle", 18, "Bold", "Mystic Water",
                new(50, 24, 39, 29, 36, 23), new(22, 15, 29, 23, 27, 14), new(18, 0, 22, 10, 16, 0),
                ["Water Gun", "Bite", "Withdraw", "Rapid Spin"], "PREVIEW"),
            Pokemon("PIKA", "Pikachu", 15, "Timid", null,
                new(38, 22, 18, 31, 24, 41), new(17, 12, 15, 25, 20, 30), new(0, 0, 0, 20, 0, 30),
                ["ThunderShock", "Growl", "Tail Whip", "Thunder Wave"], "PREVIEW"),
            empty, empty, empty, empty,
        ]);
        return (you, partner);
    }

    private static PokemonPreviewViewData Pokemon(
        string nickname, string species, int level, string nature, string? heldItem,
        BattleStats stats, SixValues ivs, SixValues evs, IReadOnlyList<string> moves, string trainer) =>
        new(nickname, species, level, nature, heldItem, stats, ivs, evs,
            moves.Select(name => new MovePreview(name)).ToArray(), new TrainerPreview(trainer));
}
