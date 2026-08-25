using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

public sealed class PublicRoomsScreenViewModel : ScreenViewModel
{
    private readonly IReadOnlyList<PublicRoomPreview> _allRooms;
    private string _searchText = "";
    private PublicSearchBy _searchBy;
    private PublicAvailabilityFilter _availability;
    private PublicGameFilter _game;
    private PublicLanguageFilter _language;
    private PublicSortOrder _sort;
    private PublicRoomPreview? _selectedRoom;
    private bool _isFilterOpen;

    public PublicRoomsScreenViewModel(MainViewModel shell) : base(shell)
    {
        _allRooms = shell.PreviewProvider.GetRooms();
        PreviewCommand = new RelayCommand(Preview, () => SelectedRoom is not null);
        ClearFiltersCommand = new RelayCommand(ClearFilters, () => HasActiveFilters);
        RefreshCommand = new RelayCommand(ApplyFilters);
        ToggleFiltersCommand = new RelayCommand(() => IsFilterOpen = !IsFilterOpen);
        CloseFiltersCommand = new RelayCommand(() => IsFilterOpen = false);
        CloseDetailsCommand = new RelayCommand(() => SelectedRoom = null);
        ApplyFilters();
    }

    public override string Title => "Browse Public Rooms";
    public ObservableCollection<PublicRoomPreview> Rooms { get; } = [];
    public IReadOnlyList<SelectionOption<PublicSearchBy>> SearchByOptions { get; } =
    [
        new(PublicSearchBy.AnyField, "Any field"), new(PublicSearchBy.RoomName, "Room name"),
        new(PublicSearchBy.Trainer, "Trainer"), new(PublicSearchBy.OfferedPokemon, "Pokémon offered"),
        new(PublicSearchBy.WantedPokemon, "Pokémon wanted"),
    ];
    public IReadOnlyList<SelectionOption<PublicAvailabilityFilter>> AvailabilityOptions { get; } =
    [new(PublicAvailabilityFilter.OpenOnly, "Open only"), new(PublicAvailabilityFilter.AllRooms, "All rooms")];
    public IReadOnlyList<SelectionOption<PublicGameFilter>> GameOptions { get; } =
    [new(PublicGameFilter.AnyGame, "Any game"), new(PublicGameFilter.FireRed, "FireRed"), new(PublicGameFilter.LeafGreen, "LeafGreen")];
    public IReadOnlyList<SelectionOption<PublicLanguageFilter>> LanguageOptions { get; } =
    [new(PublicLanguageFilter.AnyLanguage, "Any language"), new(PublicLanguageFilter.English, "English"), new(PublicLanguageFilter.Japanese, "Japanese"), new(PublicLanguageFilter.French, "French")];
    public IReadOnlyList<SelectionOption<PublicSortOrder>> SortOptions { get; } =
    [new(PublicSortOrder.BestMatch, "Best match"), new(PublicSortOrder.LowestLatency, "Lowest latency"), new(PublicSortOrder.RecentlyOpened, "Recently opened")];

    public string SearchText { get => _searchText; set { if (Set(ref _searchText, value)) ApplyFilters(); } }
    public PublicSearchBy SearchBy { get => _searchBy; set { if (Set(ref _searchBy, value)) ApplyFilters(); } }
    public PublicAvailabilityFilter Availability { get => _availability; set { if (Set(ref _availability, value)) FiltersChanged(); } }
    public PublicGameFilter Game { get => _game; set { if (Set(ref _game, value)) FiltersChanged(); } }
    public PublicLanguageFilter Language { get => _language; set { if (Set(ref _language, value)) FiltersChanged(); } }
    public PublicSortOrder Sort { get => _sort; set { if (Set(ref _sort, value)) ApplyFilters(); } }
    public PublicRoomPreview? SelectedRoom
    {
        get => _selectedRoom;
        set
        {
            if (!Set(ref _selectedRoom, value)) return;
            OnPropertyChanged(nameof(HasSelection));
            PreviewCommand.RaiseCanExecuteChanged();
        }
    }
    public bool IsFilterOpen { get => _isFilterOpen; set => Set(ref _isFilterOpen, value); }
    public bool HasSelection => SelectedRoom is not null;
    public bool HasRooms => Rooms.Count > 0;
    public bool HasActiveFilters => Availability != PublicAvailabilityFilter.OpenOnly ||
                                    Game != PublicGameFilter.AnyGame ||
                                    Language != PublicLanguageFilter.AnyLanguage;
    public int ActiveFilterCount =>
        (Availability != PublicAvailabilityFilter.OpenOnly ? 1 : 0) +
        (Game != PublicGameFilter.AnyGame ? 1 : 0) +
        (Language != PublicLanguageFilter.AnyLanguage ? 1 : 0);
    public string FilterButtonText => ActiveFilterCount == 0 ? "Filters" : $"Filters ({ActiveFilterCount})";
    public RelayCommand PreviewCommand { get; }
    public RelayCommand ClearFiltersCommand { get; }
    public RelayCommand RefreshCommand { get; }
    public RelayCommand ToggleFiltersCommand { get; }
    public RelayCommand CloseFiltersCommand { get; }
    public RelayCommand CloseDetailsCommand { get; }

    internal void ApplyFilters()
    {
        var selectedId = SelectedRoom?.PreviewId;
        IEnumerable<PublicRoomPreview> query = _allRooms;
        if (Availability == PublicAvailabilityFilter.OpenOnly)
            query = query.Where(room => room.Availability == PreviewAvailability.Open);
        if (Game != PublicGameFilter.AnyGame)
            query = query.Where(room => GameMatches(room.Game, Game));
        if (Language != PublicLanguageFilter.AnyLanguage)
            query = query.Where(room => LanguageMatches(room.Language, Language));
        if (!string.IsNullOrWhiteSpace(SearchText))
        {
            var text = SearchText.Trim();
            query = query.Where(room => SearchBy switch
            {
                PublicSearchBy.RoomName => Contains(room.RoomName, text),
                PublicSearchBy.Trainer => Contains(room.TrainerDisplayName, text),
                PublicSearchBy.OfferedPokemon => Contains(room.Offering, text),
                PublicSearchBy.WantedPokemon => Contains(room.Wanted, text),
                _ => Contains(room.RoomName, text) || Contains(room.TrainerDisplayName, text) ||
                     Contains(room.Offering, text) || Contains(room.Wanted, text),
            });
        }
        query = Sort switch
        {
            PublicSortOrder.LowestLatency => query.OrderBy(room => room.LatencyMs),
            PublicSortOrder.RecentlyOpened => query.OrderByDescending(room => room.CreatedAt),
            _ => query.OrderBy(room => room.Availability != PreviewAvailability.Open).ThenBy(room => room.LatencyMs),
        };
        var filtered = query.ToArray();
        Rooms.Clear();
        foreach (var room in filtered) Rooms.Add(room);
        SelectedRoom = selectedId is null ? null : Rooms.FirstOrDefault(room => room.PreviewId == selectedId);
        OnPropertyChanged(nameof(HasRooms));
    }

    private static bool Contains(string value, string text) =>
        value.Contains(text, StringComparison.CurrentCultureIgnoreCase);

    private static bool GameMatches(GameVersionChoice roomGame, PublicGameFilter filter) => filter switch
    {
        PublicGameFilter.FireRed => roomGame == GameVersionChoice.FireRed,
        PublicGameFilter.LeafGreen => roomGame == GameVersionChoice.LeafGreen,
        _ => true,
    };

    private static bool LanguageMatches(GameLanguage roomLanguage, PublicLanguageFilter filter) => filter switch
    {
        PublicLanguageFilter.English => roomLanguage == GameLanguage.English,
        PublicLanguageFilter.Japanese => roomLanguage == GameLanguage.Japanese,
        PublicLanguageFilter.French => roomLanguage == GameLanguage.French,
        _ => true,
    };

    private void FiltersChanged()
    {
        OnPropertyChanged(nameof(HasActiveFilters));
        OnPropertyChanged(nameof(ActiveFilterCount));
        OnPropertyChanged(nameof(FilterButtonText));
        ClearFiltersCommand.RaiseCanExecuteChanged();
        ApplyFilters();
    }

    private void ClearFilters()
    {
        _availability = PublicAvailabilityFilter.OpenOnly;
        _game = PublicGameFilter.AnyGame;
        _language = PublicLanguageFilter.AnyLanguage;
        OnPropertyChanged(nameof(Availability));
        OnPropertyChanged(nameof(Game));
        OnPropertyChanged(nameof(Language));
        FiltersChanged();
    }

    private void Preview()
    {
        if (SelectedRoom is not null) Shell.OpenDemoRoom(SelectedRoom);
    }

    public override bool DismissTemporaryLayer()
    {
        if (!IsFilterOpen) return false;
        IsFilterOpen = false;
        return true;
    }
}

public enum SettingsSection { Connection, Support, Advanced }

public sealed class SettingsScreenViewModel : ScreenViewModel
{
    private string _statusMessage = "";
    private string _supportFilePath = "";
    private SettingsSection _selectedSection;

    public SettingsScreenViewModel(MainViewModel shell) : base(shell)
    {
        RecheckCommand = new AsyncCommand(LoadAsync);
        SupportCommand = new AsyncCommand(CreateSupportAsync, () => IsServiceReady);
        CopySupportPathCommand = new RelayCommand(
            () => Shell.Copy(SupportFilePath, "Support file location copied"), () => HasSupportFile);
    }

    public override string Title => "Settings";
    public IReadOnlyList<SelectionOption<SettingsSection>> Sections { get; } =
    [
        new(SettingsSection.Connection, "Connection"),
        new(SettingsSection.Support, "Support"),
        new(SettingsSection.Advanced, "Advanced"),
    ];
    public SettingsSection SelectedSection { get => _selectedSection; set => Set(ref _selectedSection, value); }
    public ObservableCollection<AdapterProfileViewData> Adapters { get; } = [];
    public string StatusMessage { get => _statusMessage; private set => Set(ref _statusMessage, value); }
    public string SupportFilePath
    {
        get => _supportFilePath;
        private set
        {
            if (!Set(ref _supportFilePath, value)) return;
            OnPropertyChanged(nameof(HasSupportFile));
            CopySupportPathCommand.RaiseCanExecuteChanged();
        }
    }
    public bool HasSupportFile => !string.IsNullOrWhiteSpace(SupportFilePath);
    public AsyncCommand RecheckCommand { get; }
    public AsyncCommand SupportCommand { get; }
    public RelayCommand CopySupportPathCommand { get; }

    public override Task OnNavigatedToAsync() => LoadAsync();

    public async Task LoadAsync()
    {
        Adapters.Clear();
        if (!IsServiceReady)
        {
            StatusMessage = "Connect the installed SwitchTrade runtime to check Wi-Fi adapters.";
            return;
        }
        try
        {
            foreach (var adapter in await Shell.Gateway.GetAdapterProfilesAsync()) Adapters.Add(adapter);
            StatusMessage = "Compatibility profiles are available. Live device selection and repair are not available yet.";
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private async Task CreateSupportAsync()
    {
        try
        {
            SupportFilePath = await Shell.Gateway.CreateSupportBundleAsync();
            StatusMessage = "Support file created.";
            Shell.Announce(StatusMessage);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        SupportCommand.RaiseCanExecuteChanged();
    }
}
