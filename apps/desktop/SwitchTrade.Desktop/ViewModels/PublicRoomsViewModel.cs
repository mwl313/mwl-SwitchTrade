using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "The navigation lifecycle cancels and replaces the request token source.")]
public sealed class PublicRoomsScreenViewModel : ScreenViewModel
{
    private CancellationTokenSource _requestCancellation = new();
    private string _searchText = "";
    private string _trainerName = "";
    private PublicAvailabilityFilter _availability;
    private PublicGameFilter _game;
    private PublicLanguageFilter _language;
    private PublicSortOrder _sort;
    private PublicRoomListing? _selectedRoom;
    private bool _isFilterOpen;
    private bool _isBusy;
    private string _errorMessage = "";

    public PublicRoomsScreenViewModel(MainViewModel shell) : base(shell)
    {
        RefreshCommand = new AsyncCommand(LoadAsync, () => IsServiceReady && !IsBusy);
        JoinCommand = new AsyncCommand(JoinAsync, CanJoin);
        ClearFiltersCommand = new RelayCommand(ClearFilters, () => HasActiveFilters);
        ToggleFiltersCommand = new RelayCommand(() => IsFilterOpen = !IsFilterOpen);
        CloseFiltersCommand = new RelayCommand(() => IsFilterOpen = false);
        CloseDetailsCommand = new RelayCommand(() => SelectedRoom = null);
    }

    public override string Title => "Browse Public Rooms";
    public ObservableCollection<PublicRoomListing> Rooms { get; } = [];
    public IReadOnlyList<SelectionOption<PublicAvailabilityFilter>> AvailabilityOptions { get; } =
    [new(PublicAvailabilityFilter.OpenOnly, "Open only"), new(PublicAvailabilityFilter.AllRooms, "All rooms")];
    public IReadOnlyList<SelectionOption<PublicGameFilter>> GameOptions { get; } =
    [new(PublicGameFilter.AnyGame, "Any game"), new(PublicGameFilter.FireRed, "FireRed"), new(PublicGameFilter.LeafGreen, "LeafGreen")];
    public IReadOnlyList<SelectionOption<PublicLanguageFilter>> LanguageOptions { get; } =
    [
        new(PublicLanguageFilter.AnyLanguage, "Any language"),
        new(PublicLanguageFilter.English, "English"),
        new(PublicLanguageFilter.Japanese, "Japanese"),
        new(PublicLanguageFilter.French, "French"),
        new(PublicLanguageFilter.German, "German"),
        new(PublicLanguageFilter.Italian, "Italian"),
        new(PublicLanguageFilter.Spanish, "Spanish"),
    ];
    public IReadOnlyList<SelectionOption<PublicSortOrder>> SortOptions { get; } =
    [
        new(PublicSortOrder.RecentlyOpened, "Recently opened"),
        new(PublicSortOrder.Oldest, "Oldest"),
        new(PublicSortOrder.RoomName, "Room name"),
    ];

    public string SearchText { get => _searchText; set => Set(ref _searchText, value); }
    public string TrainerName
    {
        get => _trainerName;
        set
        {
            if (!Set(ref _trainerName, value)) return;
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public PublicAvailabilityFilter Availability
    {
        get => _availability;
        set { if (Set(ref _availability, value)) FiltersChanged(); }
    }
    public PublicGameFilter Game
    {
        get => _game;
        set { if (Set(ref _game, value)) FiltersChanged(); }
    }
    public PublicLanguageFilter Language
    {
        get => _language;
        set { if (Set(ref _language, value)) FiltersChanged(); }
    }
    public PublicSortOrder Sort { get => _sort; set => Set(ref _sort, value); }
    public PublicRoomListing? SelectedRoom
    {
        get => _selectedRoom;
        set
        {
            if (!Set(ref _selectedRoom, value)) return;
            OnPropertyChanged(nameof(HasSelection));
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public bool IsFilterOpen { get => _isFilterOpen; set => Set(ref _isFilterOpen, value); }
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (!Set(ref _isBusy, value)) return;
            RefreshCommand.RaiseCanExecuteChanged();
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public string ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (!Set(ref _errorMessage, value)) return;
            OnPropertyChanged(nameof(HasError));
        }
    }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public bool HasSelection => SelectedRoom is not null;
    public bool HasRooms => Rooms.Count > 0;
    public bool ShowEmptyState => !IsBusy && !HasError && !HasRooms;
    public bool HasActiveFilters => Availability != PublicAvailabilityFilter.OpenOnly ||
                                    Game != PublicGameFilter.AnyGame ||
                                    Language != PublicLanguageFilter.AnyLanguage;
    public int ActiveFilterCount =>
        (Availability != PublicAvailabilityFilter.OpenOnly ? 1 : 0) +
        (Game != PublicGameFilter.AnyGame ? 1 : 0) +
        (Language != PublicLanguageFilter.AnyLanguage ? 1 : 0);
    public string FilterButtonText => ActiveFilterCount == 0 ? "Filters" : $"Filters ({ActiveFilterCount})";
    public AsyncCommand RefreshCommand { get; }
    public AsyncCommand JoinCommand { get; }
    public RelayCommand ClearFiltersCommand { get; }
    public RelayCommand ToggleFiltersCommand { get; }
    public RelayCommand CloseFiltersCommand { get; }
    public RelayCommand CloseDetailsCommand { get; }

    public override Task OnNavigatedToAsync()
    {
        if (_requestCancellation.IsCancellationRequested)
        {
            _requestCancellation.Dispose();
            _requestCancellation = new CancellationTokenSource();
        }
        return LoadAsync();
    }

    public override void OnNavigatedFrom() => _requestCancellation.Cancel();

    private async Task LoadAsync()
    {
        if (!Shell.IsPublicDirectoryAvailable)
        {
            ErrorMessage = "Public rooms are unavailable with this SwitchTrade runtime.";
            return;
        }
        var selectedId = SelectedRoom?.ListingId;
        try
        {
            IsBusy = true;
            ErrorMessage = "";
            var rooms = await Shell.Gateway.GetPublicRoomsAsync(new PublicRoomQuery(
                SearchText, Availability, Game, Language, Sort), _requestCancellation.Token);
            if (!ReferenceEquals(Shell.CurrentScreen, this)) return;
            Rooms.Clear();
            foreach (var room in rooms) Rooms.Add(room);
            SelectedRoom = selectedId is null
                ? Rooms.FirstOrDefault()
                : Rooms.FirstOrDefault(room => room.ListingId == selectedId) ?? Rooms.FirstOrDefault();
            NotifyCollectionState();
        }
        catch (OperationCanceledException) when (_requestCancellation.IsCancellationRequested) { }
        catch (UserFacingException error) { ErrorMessage = error.UserMessage; }
        finally
        {
            IsBusy = false;
            NotifyCollectionState();
        }
    }

    private bool CanJoin() => !IsBusy && IsServiceReady &&
                              TrainerName.Trim().Length is >= 1 and <= 20 &&
                              SelectedRoom?.IsOpen == true;

    private async Task JoinAsync()
    {
        if (SelectedRoom is not { } selected) return;
        try
        {
            IsBusy = true;
            ErrorMessage = "";
            var room = await Shell.Gateway.JoinPublicRoomAsync(
                selected.ListingId, TrainerName, _requestCancellation.Token);
            if (!ReferenceEquals(Shell.CurrentScreen, this)) return;
            Shell.OpenTradeRoom(room, RoomMembershipRole.Member, SwitchRoomRole.Unassigned);
        }
        catch (OperationCanceledException) when (_requestCancellation.IsCancellationRequested) { }
        catch (UserFacingException error)
        {
            ErrorMessage = error.UserMessage;
            await LoadAsync();
        }
        finally { IsBusy = false; }
    }

    private void FiltersChanged()
    {
        OnPropertyChanged(nameof(HasActiveFilters));
        OnPropertyChanged(nameof(ActiveFilterCount));
        OnPropertyChanged(nameof(FilterButtonText));
        ClearFiltersCommand.RaiseCanExecuteChanged();
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

    private void NotifyCollectionState()
    {
        OnPropertyChanged(nameof(HasRooms));
        OnPropertyChanged(nameof(ShowEmptyState));
    }

    public override bool DismissTemporaryLayer()
    {
        if (!IsFilterOpen) return false;
        IsFilterOpen = false;
        return true;
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        RefreshCommand.RaiseCanExecuteChanged();
        JoinCommand.RaiseCanExecuteChanged();
    }
}
