using SwitchTrade.Desktop.Models;

namespace SwitchTrade.Desktop.Services;

public sealed class PublicRoomPreviewProvider
{
    public IReadOnlyList<PublicRoomSummary> GetRooms()
    {
        var now = DateTimeOffset.UtcNow;
        return
        [
            new("demo-1", "Kanto afternoon trades", "Leaf", "FireRed", "English",
                "Bulbasaur", "Any version exclusive", "East Asia", "Open", 42, now.AddMinutes(-6),
                "One relaxed trade before dinner."),
            new("demo-2", "Complete the Pokédex", "GreenTrainer", "LeafGreen", "English",
                "Pinsir", "Scyther", "North America", "Open", 88, now.AddMinutes(-18),
                "Version-exclusive swaps welcome."),
            new("demo-3", "Late-night link club", "MAY", "FireRed", "Japanese",
                "Dratini", "Starter Pokémon", "East Asia", "Open", 61, now.AddMinutes(-29),
                "日本語 / English is okay."),
            new("demo-4", "Berry and item trades", "Nora", "LeafGreen", "French",
                "Chansey", "Anything", "Europe", "Open", 117, now.AddMinutes(-44),
                "Held-item trades are fine."),
            new("demo-5", "Quick version swap", "Red", "FireRed", "English",
                "Growlithe", "Vulpix", "Oceania", "Full", 154, now.AddHours(-1),
                "Room currently has two trainers."),
        ];
    }

    public (PartyPanelViewData You, PartyPanelViewData Partner) GetSampleParties()
    {
        var empty = new PokemonViewData("", "", 0, "", "", "", "", "", "", "", true);
        var you = new PartyPanelViewData("You", "Blue",
        [
            new("BULBY", "Bulbasaur", 18, "Calm", "Oran Berry", "HP 49 · Atk 25 · Def 27 · SpA 33 · SpD 38 · Spe 24", "20 / 14 / 19 / 25 / 28 / 17", "12 / 0 / 8 / 20 / 16 / 0", "Vine Whip · Sleep Powder · Leech Seed · Tackle", "OT: SAMPLE"),
            new("RATTA", "Rattata", 12, "Jolly", "None", "HP 32 · Atk 23 · Def 15 · SpA 12 · SpD 16 · Spe 29", "18 / 24 / 13 / 8 / 17 / 27", "0 / 12 / 0 / 0 / 0 / 18", "Quick Attack · Tail Whip · Hyper Fang · Focus Energy", "OT: SAMPLE"),
            empty, empty, empty, empty,
        ]);
        var partner = new PartyPanelViewData("Partner", "Teal",
        [
            new("SHELLY", "Squirtle", 18, "Bold", "Mystic Water", "HP 50 · Atk 24 · Def 39 · SpA 29 · SpD 36 · Spe 23", "22 / 15 / 29 / 23 / 27 / 14", "18 / 0 / 22 / 10 / 16 / 0", "Water Gun · Bite · Withdraw · Rapid Spin", "OT: PREVIEW"),
            new("PIKA", "Pikachu", 15, "Timid", "None", "HP 38 · Atk 22 · Def 18 · SpA 31 · SpD 24 · Spe 41", "17 / 12 / 15 / 25 / 20 / 30", "0 / 0 / 0 / 20 / 0 / 30", "ThunderShock · Growl · Tail Whip · Thunder Wave", "OT: PREVIEW"),
            empty, empty, empty, empty,
        ]);
        return (you, partner);
    }
}
