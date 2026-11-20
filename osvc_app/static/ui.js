document.addEventListener('DOMContentLoaded', function () {
  window.osvcToast=function(message){var toast=document.createElement('p');toast.className='flash success app-toast';toast.setAttribute('role','status');toast.textContent=message;document.querySelector('.toast-stack').append(toast);setTimeout(()=>toast.remove(),2000);};
  document.querySelectorAll('[data-toast]').forEach(function (toast) { setTimeout(function () { toast.remove(); }, 2000); });
  document.querySelectorAll('select').forEach(function (select) {
    if (select.multiple || select.size > 1 || select.closest('.select-control')) return;
    var wrapper=document.createElement('span');wrapper.className='select-control';select.before(wrapper);wrapper.append(select);
  });
  // Measure the actual full-label menu; the measuring copy never enters layout/focus.
  var appHeader=document.querySelector('.app-header');
  if(appHeader){
    var nav=appHeader.querySelector('.app-nav'),measure=nav.cloneNode(true);
    measure.classList.add('nav-measure');measure.inert=true;measure.setAttribute('aria-hidden','true');appHeader.append(measure);
    var inner=appHeader.querySelector('.app-nav-inner'),main=appHeader.querySelector('.app-nav-main');
    function fitNavigation(){
      var css=getComputedStyle(inner),mainCss=getComputedStyle(main),actions=appHeader.querySelector('.header-actions');
      var needed=appHeader.querySelector('.brand').getBoundingClientRect().width+actions.getBoundingClientRect().width+measure.getBoundingClientRect().width+(parseFloat(css.columnGap)||0)+(parseFloat(mainCss.columnGap)||0)+parseFloat(css.paddingLeft)+parseFloat(css.paddingRight);
      appHeader.classList.toggle('nav-compact',needed>inner.clientWidth);
    }
    new ResizeObserver(fitNavigation).observe(inner);document.fonts.ready.then(fitNavigation);fitNavigation();
    nav.querySelectorAll('a').forEach(a=>{if(a.classList.contains('active'))a.setAttribute('aria-current','page');});
    // bez bubliny po najetí myší: ikony v menu a hlavičce mají jen aria-label (pro čtečky obrazovky)
  }

  document.querySelectorAll('table.responsive-table').forEach(function (table) {
    var headers = Array.from(table.querySelectorAll('thead th')).map(function (cell) { return cell.textContent.trim(); });
    table.querySelectorAll('tbody tr').forEach(function (row) {
      Array.from(row.children).forEach(function (cell, index) { if (!cell.hasAttribute('data-label') && headers[index]) cell.setAttribute('data-label', headers[index]); });
    });
  });
  document.querySelectorAll('[data-dashboard-item], [data-dashboard-trip]').forEach(function (row) {
    function openItem(event) { if (event.target.closest('a,button,form')) return; window.location.href = row.dataset.dashboardItem || row.dataset.dashboardTrip; }
    row.addEventListener('click', openItem);
    row.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openItem(event); } });
  });

  var params = new URLSearchParams(window.location.search);
  var settingsTabs = Array.from(document.querySelectorAll('[data-settings-tab]'));
  if (settingsTabs.length) {
    var settingsPanels = Array.from(document.querySelectorAll('[data-settings-panel]'));
    var tabsRoot = document.querySelector('[data-settings-tabs]');
    var defaultTab = tabsRoot?.dataset.defaultTab;
    var settingsStorageKey = defaultTab ? 'osvc:tabs:' + location.pathname : 'osvc:settings-tab';
    var validSettingsTab = function (key) { return settingsTabs.some(function (tab) { return tab.dataset.settingsTab === key; }); };
    var tabForLocation = function () {
      var requested = params.get('tab') || params.get('section') || window.location.hash.replace(/^#/, '');
      if (requested && requested.indexOf('profile-') === 0 && validSettingsTab('profile')) return 'profile';
      if (requested && requested.indexOf('vehicle-') === 0) return 'vehicles';
      return validSettingsTab(requested) ? requested : '';
    };
    var activateSettingsTab = function (key, updateUrl) {
      if (!validSettingsTab(key)) key = settingsTabs[0].dataset.settingsTab;
      settingsTabs.forEach(function (tab) {
        var active = tab.dataset.settingsTab === key;
        tab.classList.toggle('is-active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.tabIndex = active ? 0 : -1;
      });
      settingsPanels.forEach(function (panel) { panel.hidden = panel.dataset.settingsPanel !== key; });
      var panelTitle = tabsRoot.querySelector("[data-panel-title]");
      if (panelTitle) panelTitle.textContent = settingsTabs.find(function(tab){return tab.dataset.settingsTab === key;}).querySelector("span:last-child").textContent;
      try { sessionStorage.setItem(settingsStorageKey, key); } catch (error) {}
      if (updateUrl) window.history.pushState({}, '', '#' + (key==='profile'?'profile-overview':key));
      document.dispatchEvent(new CustomEvent('settings-tab-change',{detail:key}));
    };
    var initialSettingsTab = tabForLocation();
    if (!initialSettingsTab && !defaultTab) {
      try { initialSettingsTab = sessionStorage.getItem(settingsStorageKey) || ''; } catch (error) {}
    }
    activateSettingsTab(initialSettingsTab || defaultTab || settingsTabs[0].dataset.settingsTab, false);
    document.querySelectorAll('[data-side-tabs-year]').forEach(function(form){form.addEventListener('submit',function(){form.action=location.pathname+(location.hash || '#' + defaultTab);});});
    settingsTabs.forEach(function (tab) {
      tab.addEventListener('click', function () { activateSettingsTab(tab.dataset.settingsTab, true); });
      tab.addEventListener('keydown', function (event) {
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        event.preventDefault();
        var index = settingsTabs.indexOf(tab);
        var next = settingsTabs[(index + (event.key === 'ArrowDown' ? 1 : -1) + settingsTabs.length) % settingsTabs.length];
        activateSettingsTab(next.dataset.settingsTab, true);
        next.focus();
      });
    });
    window.addEventListener('hashchange', function () {
      var selected = tabForLocation();
      activateSettingsTab(selected || defaultTab || settingsTabs[0].dataset.settingsTab, false);
    });
    document.querySelectorAll('[data-settings-panel] form').forEach(function (form) {
      form.addEventListener('submit', function () {
        var panel = form.closest('[data-settings-panel]');
        if (panel) try { sessionStorage.setItem(settingsStorageKey, panel.dataset.settingsPanel); } catch (error) {}
      });
    });
    var settingsTarget = window.location.hash.replace(/^#/, '');
    if (settingsTarget.indexOf('vehicle-') === 0) {
      var vehicle = document.getElementById(settingsTarget);
      if (vehicle) {
        var disclosure = vehicle.querySelector('details');
        if (disclosure) disclosure.open = true;
        vehicle.scrollIntoView({block: 'center'});
      }
    }
  }
  if (window.location.hash === '#manual-income') {
    var manualIncome = document.getElementById('manual-income');
    if (manualIncome) manualIncome.open = true;
  }
  document.querySelectorAll('[data-open-manual-income]').forEach(function (button) { button.addEventListener('click', function () { var form=document.querySelector('#manual-income'); if(form){form.open=true;form.scrollIntoView({behavior:'smooth',block:'start'});} }); });
  document.querySelectorAll('[data-open-vehicle]').forEach(function (button) { button.addEventListener('click', function () { var panel=document.querySelector('[data-vehicle-panel]'); if(panel){ panel.open=true; panel.scrollIntoView({behavior:'smooth',block:'nearest'}); var first=panel.querySelector('input[name="name"]'); if(first) first.focus({preventScroll:true}); } }); });
  var addressTabs = document.querySelectorAll('[data-address-tab]');
  if (addressTabs.length) {
    function activateAddress(key) {
      if (!Array.from(addressTabs).some(t => t.dataset.addressTab === key)) key='suppliers';
      addressTabs.forEach(t => {const active=t.dataset.addressTab===key;t.classList.toggle('is-active',active);t.setAttribute('aria-selected',String(active));t.tabIndex=active?0:-1;});
      document.querySelectorAll('[data-address-panel]').forEach(p => p.hidden=p.dataset.addressPanel!==key);
      var searchForm=document.querySelector('.address-toolbar');if(searchForm)searchForm.action=searchForm.action.split('#')[0]+'#'+key;
      try{sessionStorage.setItem('osvc:address-tab',key);}catch(e){}
    }
    let savedTab='';try{savedTab=sessionStorage.getItem('osvc:address-tab')||'';}catch(e){}
    activateAddress(location.hash.slice(1)||savedTab);
    addressTabs.forEach((tab,index)=>{
      tab.addEventListener('click',()=>{activateAddress(tab.dataset.addressTab);history.replaceState(null,'','#'+tab.dataset.addressTab);});
      tab.addEventListener('keydown',event=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const next=addressTabs[(index+(['ArrowUp','ArrowLeft'].includes(event.key)?-1:1)+addressTabs.length)%addressTabs.length];next.click();next.focus();});
    });
  }
  document.querySelectorAll('.address-edit-cancel').forEach(function (button) { button.addEventListener('click', function () { var form=button.closest('form'); var panel=button.closest('.address-edit-panel'); if (form) form.reset(); if (panel) panel.open=false; }); });
  var savedKey = params.get('draft_saved');
  if (savedKey) {
    localStorage.removeItem('osvc-draft:' + savedKey);
    params.delete('draft_saved');
    var clean = window.location.pathname + (params.toString() ? '?' + params.toString() : '') + window.location.hash;
    window.history.replaceState({}, '', clean);
  }

  function guardSnapshot(form) {
    return JSON.stringify(Array.from(form.elements).filter(function (field) {
      return field.name && !field.disabled && field.type !== 'hidden' && field.type !== 'submit' && field.type !== 'button';
    }).map(function (field) {
      if (field.type === 'file') return [field.name, field.files && field.files.length ? Array.from(field.files).map(function (file) { return [file.name,file.size,file.lastModified]; }) : []];
      if (field.type === 'checkbox' || field.type === 'radio') return [field.name, field.checked];
      return [field.name, field.value];
    }));
  }

  document.querySelectorAll('form[data-draft-form]').forEach(function (form) {
    form._dirtyInitialState = guardSnapshot(form);
    var storageKey = 'osvc-draft:' + form.dataset.draftKey;
    var status = form.querySelector('.draft-status');
    var restored;
    try { restored = JSON.parse(localStorage.getItem(storageKey)); } catch (error) { restored = null; }

    if (restored && restored.values) {
      Object.keys(restored.values).forEach(function (name) {
        var field = form.elements.namedItem(name);
        if (!field || field.type === 'file' || field.type === 'hidden') return;
        if (field.type === 'checkbox' || field.type === 'radio') field.checked = Boolean(restored.values[name]);
        else field.value = restored.values[name];
      });
      if (status) {
        status.textContent = 'Rozepsaný záznam obnoven' + (restored.fileSelected ? ' – soubor je potřeba znovu vybrat' : '');
        status.hidden = false;
      }
      var wrapper = form.closest('details');
      if (wrapper) wrapper.open = true;
    }

    function saveDraft() {
      var values = {};
      var fileSelected = restored ? Boolean(restored.fileSelected) : false;
      Array.from(form.elements).forEach(function (field) {
        if (!field.name || field.type === 'hidden' || field.type === 'submit' || field.type === 'button') return;
        if (field.type === 'file') {
          if (field.files && field.files.length) fileSelected = true;
          return;
        }
        values[field.name] = field.type === 'checkbox' || field.type === 'radio' ? field.checked : field.value;
      });
      restored = {values: values, fileSelected: fileSelected};
      localStorage.setItem(storageKey, JSON.stringify(restored));
    }

    form.addEventListener('input', saveDraft);
    form.addEventListener('change', saveDraft);
  });

  var dirtyForms = Array.from(document.querySelectorAll('form[data-dirty-guard]'));
  var allowNavigation = false;
  var beforeUnloadHandler = function (event) {
    if (allowNavigation) return;
    event.preventDefault(); event.returnValue = '';
  };
  var beforeUnloadAttached = false;
  function hasDirtyForm() { return dirtyForms.some(function (form) { return form._dirty === true; }); }
  function refreshBeforeUnload() {
    var shouldAttach = hasDirtyForm();
    if (shouldAttach && !beforeUnloadAttached) { window.addEventListener('beforeunload', beforeUnloadHandler); beforeUnloadAttached = true; }
    if (!shouldAttach && beforeUnloadAttached) { window.removeEventListener('beforeunload', beforeUnloadHandler); beforeUnloadAttached = false; }
  }
  function updateDirty(form) { form._dirty = guardSnapshot(form) !== form._dirtyInitialState; refreshBeforeUnload(); }
  function discardDirtyForms() {
    allowNavigation = true;
    dirtyForms.forEach(function (form) {
      if (!form._dirty) return;
      form._dirty = false;
      var key = form.dataset.draftKey;
      if (key) localStorage.removeItem('osvc-draft:' + key);
    });
    refreshBeforeUnload();
  }
  dirtyForms.forEach(function (form) {
    if (form._dirtyInitialState === undefined) form._dirtyInitialState = guardSnapshot(form);
    form._dirty = false;
    ['input','change'].forEach(function (eventName) { form.addEventListener(eventName, function () { updateDirty(form); }); });
    form.addEventListener('submit', function () { allowNavigation = true; form._dirty = false; refreshBeforeUnload(); });
    updateDirty(form);
  });
  document.querySelectorAll('.sync-icon-form').forEach(function (form) {
    form.addEventListener('submit', function () {
      var button = form.querySelector('.sync-icon');
      if (!button || button.disabled) return;
      button.disabled = true;
      button.classList.add('sync-loading');
      button.setAttribute('aria-busy', 'true');
    });
  });
  var dirtyConfirm = document.getElementById('dirty-form-confirm');
  var pendingNavigation = null;
  function closeDirtyConfirm() { if (dirtyConfirm) dirtyConfirm.hidden = true; pendingNavigation = null; }
  if (dirtyConfirm) {
    dirtyConfirm.querySelector('[data-dirty-stay]').addEventListener('click', closeDirtyConfirm);
    dirtyConfirm.querySelector('[data-dirty-leave]').addEventListener('click', function () { var target=pendingNavigation; discardDirtyForms(); closeDirtyConfirm(); if(target) window.location.href=target; });
    dirtyConfirm.addEventListener('click', function (event) { if (event.target === dirtyConfirm) closeDirtyConfirm(); });
  }
  document.addEventListener('click', function (event) {
    var link=event.target.closest('a[href]');
    if (!link || !hasDirtyForm() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target === '_blank' || link.hasAttribute('download')) return;
    var url=new URL(link.href,window.location.href);
    if (url.origin !== window.location.origin || url.href === window.location.href) return;
    // Profile sections share one form; changing the visible section discards nothing.
    if(url.pathname===location.pathname && url.search===location.search && url.hash.startsWith('#profile-')) return;
    event.preventDefault(); pendingNavigation=url.href;
    if (dirtyConfirm) { dirtyConfirm.hidden=false; dirtyConfirm.querySelector('[data-dirty-stay]').focus({preventScroll:true}); }
    else if (window.confirm('Formulář obsahuje neuložené změny. Opravdu chcete stránku opustit?')) window.location.href=url.href;
  }, true);

  document.querySelectorAll('[data-combobox]').forEach(function (box) {
    var input = box.querySelector('input[role="combobox"]');
    var hidden = document.getElementById(box.dataset.hiddenInput) || box.closest('form').elements.counterparty_id;
    var toggle = box.querySelector('.combobox-toggle');
    var list = box.querySelector('.combobox-options');
    var verify=box.querySelector('.combobox-verify');
    if(verify){
      verify.updateAvailability=function(){verify.disabled=Boolean(verify.dataset.busy)||input.value.trim().length<2;};
      input.addEventListener('input',verify.updateAvailability);
      input.addEventListener('change',verify.updateAvailability);
      verify.updateAvailability();
      verify.addEventListener('click',function(event){event.preventDefault();closeList();});
    }
    var options = Array.from(list.querySelectorAll('[role="option"]'));
    function normalize(value) { return value.trim().replace(/\s+/g, ' ').toLocaleLowerCase('cs'); }
    var activeIndex=-1;list.id=list.id || input.id+'-options';input.setAttribute('aria-controls',list.id);
    options.forEach(function(option,index){option.id=list.id+'-'+index;option.tabIndex=-1;});
    function openList() { list.hidden = false; input.setAttribute('aria-expanded', 'true'); }
    function closeList() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');activeIndex=-1;options.forEach(o=>o.setAttribute('aria-selected','false')); }
    function filterOptions() {
      var needle = normalize(input.value); var visible = 0; var exact = [];
      options.forEach(function (option) {
        var name = normalize(option.dataset.name); var show = !needle || normalize(option.dataset.search || option.dataset.name).includes(needle);
        option.hidden = !show; if (show) visible += 1; if (name === needle) exact.push(option);
      });
      if (hidden) { var selected=exact.find(o=>o.dataset.value===hidden.value);hidden.value=selected?selected.dataset.value:(exact.length===1?exact[0].dataset.value:''); }
      if (visible === 0) closeList();
      return visible;
    }
    function choose(option) {
      input.value = option.dataset.name;
      if (hidden) hidden.value = option.dataset.value || '';
      filterOptions();
      closeList();
      input.dispatchEvent(new Event('input',{bubbles:true}));closeList();
      box.dispatchEvent(new CustomEvent('combobox:choose',{detail:{value:option.dataset.value,name:option.dataset.name}}));
      input.focus({preventScroll: true});closeList();
      window.requestAnimationFrame(function () {
        input.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});
      });
    }
    filterOptions();
    input.addEventListener('focus', function () { if (filterOptions()) openList(); });
    input.addEventListener('input', function () { if (filterOptions()) openList(); });
    toggle.addEventListener('click', function () { if (list.hidden) { if (filterOptions()) openList(); input.focus(); } else closeList(); });
    list.addEventListener('click',function(event){var option=event.target.closest('[role="option"]');if(option && list.contains(option))choose(option);});
    box.addEventListener('combobox:options',function(event){
      list.replaceChildren();options=event.detail.map(function(item,index){
        var option=document.createElement('button');option.type='button';option.setAttribute('role','option');option.dataset.value=item.ico;option.dataset.name=item.name;option.id=list.id+'-'+index;option.tabIndex=-1;
        var title=document.createElement('span');title.textContent=item.name;var detail=document.createElement('small');detail.textContent='IČO '+item.ico+' · '+item.address;option.append(title,detail);list.append(option);return option;
      });if(filterOptions())openList();
    });
    input.addEventListener('keydown', function (event) {
      var visible = options.filter(function (option) { return !option.hidden; });
      if (event.key === 'Escape') { event.preventDefault();closeList(); }
      if (['ArrowDown','ArrowUp'].includes(event.key) && visible.length) {
        event.preventDefault();openList();activeIndex=(activeIndex+(event.key==='ArrowDown'?1:-1)+visible.length)%visible.length;
        options.forEach(o=>o.setAttribute('aria-selected','false'));
        visible[activeIndex].setAttribute('aria-selected','true');input.setAttribute('aria-activedescendant',visible[activeIndex].id);visible[activeIndex].scrollIntoView({block:'nearest'});
      }
      if (event.key === 'Enter' && !list.hidden && activeIndex>=0 && visible[activeIndex]) { event.preventDefault();choose(visible[activeIndex]); }

    });
    document.addEventListener('click', function (event) { if (!box.contains(event.target)) closeList(); });
  });

  var multiDayToggle = document.querySelector('[data-multi-day-toggle]');
  if (multiDayToggle) {
    var startDate = document.getElementById('trip_date');
    var endDate = document.getElementById('trip_end_date');
    var endWrapper = document.querySelector('[data-trip-end-wrapper]');
    multiDayToggle.checked = Boolean(endDate.value && startDate.value && endDate.value !== startDate.value);
    endDate.disabled = !multiDayToggle.checked;
    endDate.placeholder = multiDayToggle.checked ? '' : 'Stejný den';
    startDate.addEventListener('input', function () { if (!multiDayToggle.checked) endDate.value = ''; });
    startDate.addEventListener('change', function () { if (!multiDayToggle.checked) endDate.value = ''; });
    multiDayToggle.addEventListener('change', function () {
      endDate.disabled = !multiDayToggle.checked;
      endDate.placeholder = multiDayToggle.checked ? '' : 'Stejný den';
      if (multiDayToggle.checked && !endDate.value) endDate.value = startDate.value;
      if (!multiDayToggle.checked) endDate.value = '';
      endDate.dispatchEvent(new Event('change', {bubbles: true}));
    });
  }

  var costBox = document.querySelector('[data-trip-cost]');
  if (costBox && document.getElementById('fuel_purchase_id')) {
    var tripForm = costBox.closest('form');
    var source = document.getElementById('fuel_purchase_id');
    var message = costBox.querySelector('[data-cost-message]');
    var messageText = costBox.querySelector('[data-cost-message-text]');
    var consumptionLink = costBox.querySelector('[data-consumption-link]');
    var fuelDateWarning = costBox.querySelector('[data-fuel-date-warning]');
    var fuelPicker = costBox.querySelector('.trip-fuel-picker');
    var fuelPickerSummary = costBox.querySelector('[data-fuel-picker-summary]');
    var costSource = costBox.querySelector('[data-cost-source]');
    var fuelChoiceLabel = costBox.querySelector('[data-fuel-choice-label]');
    var fuelClear = costBox.querySelector('[data-fuel-clear]');
    var values = costBox.querySelector('.trip-cost-values');
    var calc = costBox.querySelector('[data-cost-calc]');
    var timer, previewRevision=0;
    function money(value) { return Number(value).toLocaleString('cs-CZ', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Kč'; }
    function decimal(value, digits) { return Number(value).toLocaleString('cs-CZ', {minimumFractionDigits: digits, maximumFractionDigits: digits}); }
    function renderCost(data) {
      if (data.fuels) {
        var selected = source.value;
        if (source.tagName === 'SELECT') {
          var defaultOption = new Option('Bez dokladu – vyhláška', '0');
          source.replaceChildren(defaultOption);
          data.fuels.forEach(function (fuel) { var option=new Option(fuel.label,String(fuel.id));option.dataset.label=fuel.label;source.add(option); });
        }
        if (source.tagName === 'SELECT' && Array.from(source.options).some(function (option) { return option.value === selected; })) source.value = selected;
        else if (selected !== '0') {
          source.value = '0';
          fuelDateWarning.hidden = false;
          window.setTimeout(function () { fuelDateWarning.hidden = true; }, 4500);
          updateCost(); return;
        }
        if (fuelPicker) fuelPicker.hidden = !data.fuels.length;
        if (fuelPickerSummary) fuelPickerSummary.textContent = source.value !== '0' ? 'Změnit účtenku PHM' : 'Použít účtenku PHM';
        if (costSource) {
          var selectedOption = source.tagName === 'SELECT' && source.options[source.selectedIndex];
          costSource.textContent = source.value !== '0' ? 'Doklad ' + ((selectedOption && (selectedOption.dataset.label||'').split(' · ')[0]) || '') : 'Vyhláška ' + (tripForm.elements.trip_date.value || '').slice(0,4);
        }
        if (fuelChoiceLabel) {
          var choice = source.tagName === 'SELECT' && source.options[source.selectedIndex];
          fuelChoiceLabel.textContent = source.value !== '0' && choice ? choice.textContent : 'Cena PHM: ' + (data.statutory_label || 'vyhláška');
        }
        if (fuelClear) fuelClear.hidden = source.value === '0' || !data.fuels.length;
      }
      if (!data.total) {
        var emptyTotalHead = costBox.querySelector('[data-cost-total-head]');
        if (emptyTotalHead) { emptyTotalHead.textContent = 'spočítá se samo'; emptyTotalHead.classList.add('is-empty'); }
        if (calc) { calc.hidden = true; calc.textContent = ''; }
        values.hidden = true; costBox.querySelectorAll('.trip-cost-values dd').forEach(function (value) { value.textContent='—'; }); message.hidden = !(data.message && tripForm.elements.trip_date.value && tripForm.elements.vehicle_id.value && (tripForm.elements.distance_km.value || data.needs_consumption)); messageText.textContent = message.hidden ? '' : data.message;
        consumptionLink.hidden = !data.needs_consumption;
        consumptionLink.href = '/settings' + (data.vehicle_id ? '#vehicle-' + data.vehicle_id : '');
        return;
      }
      message.hidden = true; consumptionLink.hidden = true; values.hidden = false;
      costBox.querySelector('[data-cost-consumption]').textContent = decimal(data.consumption, 1) + ' l/100 km';
      costBox.querySelector('[data-cost-rate]').textContent = money(data.base_rate) + '/km';
      costBox.querySelector('[data-cost-price]').textContent = money(data.fuel_price) + '/l';
      costBox.querySelector('[data-cost-base]').textContent = money(data.base);
      costBox.querySelector('[data-cost-fuel]').textContent = money(data.fuel);
      costBox.querySelector('[data-cost-total]').textContent = money(data.total);
      var totalHead = costBox.querySelector('[data-cost-total-head]');
      if (totalHead) { totalHead.textContent = money(data.total); totalHead.classList.remove('is-empty'); }
      if (calc) {   // jeden řádek výpočtu: „50 km × 5,60 Kč + PHM 1,56 Kč/km“
        var km = Number(String(tripForm.elements.distance_km.value || '0').replace(/\s/g, '').replace(',', '.'));
        calc.textContent = decimal(km, km % 1 ? 1 : 0) + ' km × ' + money(data.base_rate) + ' + PHM ' + money(Number(data.consumption) * Number(data.fuel_price) / 100) + '/km';
        calc.hidden = false;
      }
    }
    function updateCost() {
      var revision=++previewRevision;
      clearTimeout(timer);
      timer = setTimeout(function () {
        var params = new URLSearchParams({vehicle_id: tripForm.elements.vehicle_id.value, trip_date: tripForm.elements.trip_date.value, trip_end_date: tripForm.elements.trip_end_date.value || tripForm.elements.trip_date.value, distance_km: tripForm.elements.distance_km.value, fuel_purchase_id: source.value || '0'});
        fetch(costBox.dataset.previewUrl + '?' + params.toString(), {headers: {'Accept': 'application/json'}})
          .then(function (response) { return response.json(); }).then(function(data){if(revision===previewRevision)renderCost(data);})
          .catch(function () { if(revision!==previewRevision)return; if (calc) calc.hidden = true; values.hidden = true; costBox.querySelectorAll('.trip-cost-values dd').forEach(function (value) { value.textContent='—'; }); message.hidden = false; messageText.textContent = 'Výpočet se nepodařilo načíst.'; consumptionLink.hidden = true; });
      }, 180);
    }
    ['vehicle_id', 'trip_date', 'trip_end_date', 'distance_km', 'fuel_purchase_id'].forEach(function (name) {
      tripForm.elements[name].addEventListener('input', updateCost);
      tripForm.elements[name].addEventListener('change', updateCost);
    });
    // An existing trip renders its immutable server snapshot immediately.
    // Recalculate only after the user changes a relevant input.
    if (tripForm.dataset.tripHasSnapshot !== 'true') updateCost();
    if (fuelClear) fuelClear.addEventListener('click', function () { source.value = '0'; source.dispatchEvent(new Event('change', {bubbles: true})); });
  }

  var previewModal = document.getElementById('document-preview-modal');
  if (previewModal) {
    var previewContent = previewModal.querySelector('.document-preview-content');
    var previewImage = previewModal.querySelector('[data-preview-image]');
    var previewPdf = previewModal.querySelector('[data-preview-pdf]');
    var previewOpen = previewModal.querySelector('[data-preview-open]');
    var previousFocus;
    function closeDocumentPreview() {
      if (previewModal.hidden) return;
      previewModal.hidden = true;
      previewImage.hidden = true; previewImage.removeAttribute('src');
      previewPdf.hidden = true; previewPdf.removeAttribute('src');
      previewOpen.hidden = true; previewOpen.removeAttribute('href');
      document.body.classList.remove('modal-open');
      if (previousFocus) previousFocus.focus({preventScroll: true});
    }
    document.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-document-preview]');
      if (!trigger) return;
      event.preventDefault(); previousFocus = trigger;
      var url = trigger.dataset.url; var mime = (trigger.dataset.mime || '').toLowerCase();
      previewImage.hidden = true; previewPdf.hidden = true; previewOpen.hidden = true;
      if (mime === 'application/pdf') {
        previewPdf.src = url; previewPdf.hidden = false;
        previewOpen.href = url; previewOpen.hidden = false;
      } else {
        previewImage.src = url; previewImage.hidden = false;
      }
      previewModal.hidden = false; document.body.classList.add('modal-open');
      previewModal.querySelector('.document-preview-close').focus({preventScroll: true});
    });
    previewModal.querySelector('.document-preview-close').addEventListener('click', closeDocumentPreview);
    previewModal.addEventListener('click', function (event) { if (event.target === previewModal) closeDocumentPreview(); });
    previewContent.addEventListener('click', function (event) { event.stopPropagation(); });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeDocumentPreview(); });
  }

  var verificationModal = document.getElementById('supplier-verification-modal');
  if (verificationModal) {
    var verificationBody = verificationModal.querySelector('[data-verification-body]');
    var verificationError = verificationModal.querySelector('[data-verification-error]');
    var verificationApply = verificationModal.querySelector('[data-verification-apply]');
    var verificationTrigger;
    function verificationLine(label, value) {
      var row = document.createElement('p'); var strong = document.createElement('strong');
      if (label) { strong.textContent = label + ': '; row.appendChild(strong); }
      row.appendChild(document.createTextNode(value || '—'));
      return row;
    }
    function closeVerification() {
      verificationModal.hidden = true; document.body.classList.remove('modal-open');
      if (verificationTrigger) verificationTrigger.focus({preventScroll: true});
    }
    function showVerificationError(message) {
      verificationError.textContent = message || 'Dodavatele se nepodařilo automaticky ověřit.';
      verificationError.hidden = false; verificationApply.hidden = true;
    }
    function renderVerification(data) {
      verificationBody.replaceChildren(); verificationError.hidden = true;
      verificationBody.appendChild(verificationLine('Současný název', data.supplier.name));
      if (data.supplier.ico) verificationBody.appendChild(verificationLine('IČO', data.supplier.ico));
      if (data.attachment) {
        var documentRow = document.createElement('div'); documentRow.className = 'verification-document';
        var documentLabel = document.createElement('strong'); documentLabel.textContent = 'Doklad k ověření';
        var documentButton = document.createElement('button'); documentButton.type = 'button'; documentButton.className = 'document-icon';
        documentButton.dataset.documentPreview = ''; documentButton.dataset.url = data.attachment.url; documentButton.dataset.mime = data.attachment.mime;
        documentButton.title = 'Zobrazit doklad'; documentButton.setAttribute('aria-label', 'Zobrazit doklad');
        documentButton.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2.75h8l4 4V21.25H6z"></path><path d="M14 2.75v4h4M9 12h6M9 16h6"></path></svg>';
        documentRow.append(documentLabel, documentButton); verificationBody.appendChild(documentRow);
      }
      if (!data.results || !data.results.length) { showVerificationError(data.message); return; }
      var heading = document.createElement('h3'); heading.textContent = data.results.length === 1 ? 'Nalezeno v ARES' : 'Vyberte správný subjekt'; verificationBody.appendChild(heading);
      var choices = document.createElement('div'); choices.className = 'verification-results';
      data.results.forEach(function (result, index) {
        var label = document.createElement('label'); var radio = document.createElement('input');
        radio.type = 'radio'; radio.name = 'verified_supplier'; radio.value = result.ico; radio.dataset.name = result.name; radio.checked = data.results.length === 1;
        var text = document.createElement('span'); text.appendChild(verificationLine('', result.name));
        text.appendChild(verificationLine('IČO', result.ico)); if (result.address) text.appendChild(verificationLine('Sídlo', result.address));
        label.append(radio, text); choices.appendChild(label);
      });
      verificationBody.appendChild(choices); verificationApply.hidden = false;
    }
    document.querySelectorAll('.verify-supplier, .verify-supplier-name').forEach(function (button) {
      button.addEventListener('click', function () {
        if(button.disabled || (button.matches('.combobox-verify') && document.getElementById(button.dataset.nameInput).value.trim().length<2)) return;
        verificationTrigger = button; verificationBody.innerHTML = '<p>Načítám údaje…</p>';
        verificationError.hidden = true; verificationApply.hidden = true; verificationModal.hidden = false; document.body.classList.add('modal-open');
        var lookupUrl = button.dataset.url;
        if (button.classList.contains('verify-supplier-name')) {
          var nameInput = document.getElementById(button.dataset.nameInput); var idInput = document.getElementById(button.dataset.idInput);
          var lookupParams = new URLSearchParams({name: nameInput.value, id: idInput.value}); lookupUrl += '?' + lookupParams.toString();
          button.dataset.selectedId = idInput.value;
        }
        fetch(lookupUrl, {headers: {'Accept': 'application/json'}}).then(function (response) {
          if (!response.ok) throw new Error(); return response.json();
        }).then(renderVerification).catch(function () { showVerificationError(); });
      });
    });
    verificationApply.addEventListener('click', function () {
      var selected = verificationModal.querySelector('input[name="verified_supplier"]:checked');
      if (!selected) { showVerificationError('Vyberte subjekt, který chcete použít.'); verificationApply.hidden = false; return; }
      if (verificationTrigger.classList.contains('verify-supplier-name') && !verificationTrigger.dataset.selectedId) {
        var nameInput = document.getElementById(verificationTrigger.dataset.nameInput);
        var idInput = document.getElementById(verificationTrigger.dataset.idInput);
        verificationApply.disabled = true;
        var nameCsrf = verificationTrigger.dataset.csrf || document.querySelector('input[name="csrf_token"]').value;
        fetch(verificationTrigger.dataset.nameApplyUrl, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, body: new URLSearchParams({csrf_token: nameCsrf, ico: selected.value})}).then(function (response) {
          return response.json().then(function (data) { if (!response.ok) throw new Error(data.message); return data; });
        }).then(function (data) {
          nameInput.value = data.supplier.name; idInput.value = data.supplier.id; closeVerification();
        }).catch(function (error) { showVerificationError(error.message); verificationApply.hidden = false; }).finally(function () { verificationApply.disabled = false; });
        return;
      }
      verificationApply.disabled = true;
      var applyUrl = verificationTrigger.dataset.applyUrl || ('/settings/suppliers/' + verificationTrigger.dataset.selectedId + '/verify/apply');
      var csrf = verificationTrigger.dataset.csrf || document.querySelector('input[name="csrf_token"]').value;
      fetch(applyUrl, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, body: new URLSearchParams({csrf_token: csrf, ico: selected.value})}).then(function (response) {
        return response.json().then(function (data) { if (!response.ok) throw new Error(data.message); return data; });
      }).then(function (data) {
        if (verificationTrigger.classList.contains('verify-supplier-name')) {
          document.getElementById(verificationTrigger.dataset.nameInput).value = data.supplier.name;
          document.getElementById(verificationTrigger.dataset.idInput).value = data.supplier.id;
        } else {
          var id = verificationTrigger.dataset.supplierId;
          var row = verificationTrigger.closest('.address-row');
          var nameNode = row && row.querySelector('.address-main strong');
          var ico = row && row.querySelector('.address-main small');
          if (nameNode) nameNode.textContent = data.supplier.name;
          if (ico && data.supplier.ico) { ico.textContent = 'IČO ' + data.supplier.ico; ico.hidden = false; }
          var editForm = row && row.querySelector('.address-edit-form');
          if (editForm && editForm.elements.name) editForm.elements.name.value = data.supplier.name;
        }
        closeVerification();
      }).catch(function (error) { showVerificationError(error.message); verificationApply.hidden = false; }).finally(function () { verificationApply.disabled = false; });
    });
    verificationModal.querySelector('[data-verification-cancel]').addEventListener('click', closeVerification);
    verificationModal.querySelector('.supplier-verification-close').addEventListener('click', closeVerification);
    verificationModal.addEventListener('click', function (event) { if (event.target === verificationModal) closeVerification(); });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape' && !verificationModal.hidden) closeVerification(); });
  }
});

// Shared help popovers used by annual report, profile and expense forms.
document.addEventListener('click',event=>{
 const trigger=event.target.closest('[popovertarget]');if(!trigger)return;
 const box=document.getElementById(trigger.getAttribute('popovertarget'));
 if(!box?.classList.contains('annual-popover'))return;
 requestAnimationFrame(()=>{if(!box.matches(':popover-open'))return;const r=trigger.getBoundingClientRect(),b=box.getBoundingClientRect();box.style.left=Math.max(8,Math.min(r.left,innerWidth-b.width-8))+'px';box.style.top=Math.max(8,Math.min(r.bottom+8,innerHeight-b.height-8))+'px';});
});
addEventListener('resize',()=>document.querySelectorAll('.annual-popover:popover-open').forEach(e=>e.hidePopover()));
// Moduly: otázka při vypínání modulu s daty – výchozí volba je Zrušit (fokus až po zobrazení záložky Moduly).
window.addEventListener('load', function () { var c = document.querySelector('[data-module-cancel]'); if (c) { c.focus({preventScroll: true}); c.closest('[data-module-confirm]').scrollIntoView({block: 'center'}); } });

// Žádné nápovědy po najetí myší (2026-11-17): atribut title – i ten, který doplní skript – se hned odstraní. Tlačítko jen
// s ikonou bez popisu dostane text do aria-label (jen pro čtečky obrazovky). Ikony (i) se otevírají kliknutím, ty zůstávají.
(function () {
  function bezTitle(el) {
    var text = el.getAttribute('title'); el.removeAttribute('title');
    if (text && !el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby') && !el.textContent.trim()) el.setAttribute('aria-label', text);
  }
  function projdi(node) {
    if (node.nodeType !== 1) return;
    if (node.hasAttribute('title')) bezTitle(node);
    node.querySelectorAll('[title]').forEach(bezTitle);
  }
  projdi(document.documentElement);
  new MutationObserver(function (zmeny) {
    zmeny.forEach(function (z) { if (z.type === 'attributes') { if (z.target.hasAttribute('title')) bezTitle(z.target); } else z.addedNodes.forEach(projdi); });
  }).observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['title']});
})();
// Režim úprav: po návratu tlačítkem Zpět (stránka z mezipaměti prohlížeče) je přepínač „Upravit“ zase vypnutý.
window.addEventListener('pageshow', function () { document.querySelectorAll('[data-edit-toggle]').forEach(function (c) { c.checked = false; }); });

/* Součet v záhlaví seznamu: pravý okraj čísla lícuje s obsahem sloupce [data-sum-column] (Kč pod Kč). Na mobilu (karty) bez posunu. */
(function () {
  var sums = [].slice.call(document.querySelectorAll('.list-heading .list-sum'));
  if (!sums.length) return;
  function align() {
    sums.forEach(function (sum) {
      sum.style.marginRight = '';
      var section = sum.closest('section'), th = section && section.querySelector('th[data-sum-column]');
      if (!th || !th.offsetParent || window.matchMedia('(max-width: 700px)').matches) return;
      var target = th.getBoundingClientRect().right - parseFloat(getComputedStyle(th).paddingRight || 0);
      var shift = sum.getBoundingClientRect().right - target;
      if (shift > 0) sum.style.marginRight = shift + 'px';
    });
  }
  align();
  window.addEventListener('resize', align);
  window.addEventListener('load', align);
  if (window.ResizeObserver) sums.forEach(function (sum) { var t = sum.closest('section') && sum.closest('section').querySelector('table'); if (t) new ResizeObserver(align).observe(t); });
  document.addEventListener('change', function (e) { if (e.target.matches && e.target.matches('[data-edit-toggle]')) align(); });
})();

/* Přepínač Upravit vypnutý: akce v seznamech se součtem a v adresářích jsou šedé a neaktivní (inert), zapnutý: normální. */
(function () {
  function sync(toggle) {
    var section = toggle.closest('section');
    if (!section || !(section.querySelector('.list-heading .list-sum') || section.classList.contains('address-section'))) return;
    section.querySelectorAll('td.akce-sloupec, .address-actions.akce-sloupec').forEach(function (cell) {
      if (!toggle.checked) cell.querySelectorAll('details[open]').forEach(function (d) { d.open = false; });
      cell.inert = !toggle.checked;
      if (toggle.checked) cell.removeAttribute('aria-disabled'); else cell.setAttribute('aria-disabled', 'true');
    });
  }
  function all() { document.querySelectorAll('.list-heading [data-edit-toggle]').forEach(sync); }
  all();
  window.addEventListener('pageshow', all);
  document.addEventListener('change', function (e) { if (e.target.matches && e.target.matches('[data-edit-toggle]')) sync(e.target); });
})();

/* Tlačítka Uložit (všude): šedá, dokud ve formuláři nejsou vyplněné všechny povinné a platné údaje. Kliknout jde dál –
   prohlížeč pak ukáže, co chybí. Platnost se čte z validity polí (bez checkValidity, aby nevznikaly události „invalid“). */
(function () {
  var buttons = [].slice.call(document.querySelectorAll('button.save-button'));
  if (!buttons.length) return;
  function complete(form) {
    for (var i = 0; i < form.elements.length; i++) {
      var el = form.elements[i];
      if (el.willValidate && !el.disabled && !el.validity.valid) return false;
    }
    return true;
  }
  var pending = false;
  function refresh() {
    pending = false;
    buttons.forEach(function (b) {
      var form = b.form; if (!form || b.disabled) return;
      var ok = complete(form);
      b.classList.toggle('is-incomplete', !ok);
      b.title = ok ? '' : 'Doplňte povinné údaje';
    });
  }
  function later() { if (!pending) { pending = true; requestAnimationFrame(refresh); } }
  refresh();
  ['input', 'change', 'reset', 'combobox:choose'].forEach(function (t) { document.addEventListener(t, later, true); });
  window.addEventListener('load', later); window.addEventListener('pageshow', later);
  setTimeout(later, 300);
})();
