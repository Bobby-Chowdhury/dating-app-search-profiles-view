from dateutil.relativedelta import relativedelta
from datetime import date
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.db.models import Q

from searchprofiles.forms import StudentSearchForm
from userprofile.models import UserProfile
from home.models import Major

#from django.conf import settings

@never_cache
def search_page(request):
    """
    The search entry page
    """

    return render(request, 'searchprofiles/search_page.html')


# STUDENT SEARCH FORM and RESULTS VIEW

@login_required
@csrf_protect
@never_cache
def student_search_form(request):

    """
    Student Search Form and Results View
    This view generates an initial queryset with the user provided input filters
    It then generates a second queryset to match the privacy preferences of the members
    in the database with respect to the searching user. An "exclude" set operation is executed
    between the first and second queryset to arrive at the "results" subset.
    This "results" subset shows users matching the criterion the user searched for while at the
    same time avoids displaying any users whose privacy filters dictate the current user not see them.
    """

    #import pdb; pdb.set_trace()

    if request.GET: # Search Form only, no data changes so the form submission is a GET request.
        form = StudentSearchForm(request.GET, request=request)
        if form.is_valid():

            #Start a Q object *args tuple collection to use for filtering the UserProfile model
            search_filter_args=()

            #get age boundaries
            today = date.today()
            srch_age_start = form.cleaned_data.get('srch_age_start', None)
            if srch_age_start:
                request.session['srch_age_start'] = srch_age_start # Extra line to set session variable to memorize form selections
                upper_dob = today - relativedelta(years=int(srch_age_start))

            srch_age_end = form.cleaned_data.get('srch_age_end', None)
            if srch_age_end:
                request.session['srch_age_end'] = srch_age_end     # Extra line to set session variable to memorize form selections
                lower_dob = today - relativedelta(years=int(srch_age_end))

            if upper_dob and lower_dob:
                # Add to the args Q object
                search_filter_args = ( Q( prof_dob__gte = lower_dob ) & Q( prof_dob__lte = upper_dob ), )


            #Start a **kwargs dictionary collection to use for filtering the UserProfile model
            search_filter_kwargs={}

            #get seeking / orientation
            srch_iam_type = form.cleaned_data.get('srch_iam_type', None)

            #Flip the search bits for MW and WM to find the sought rather than the seeker's orientation
            if srch_iam_type:
                if srch_iam_type == 'MW':
                    srch_iam_type = 'WM'
                elif srch_iam_type == 'WM':
                    srch_iam_type = 'MW'

                search_filter_kwargs['prof_iam_type'] = srch_iam_type


            #get country, state, college

            #Add the country to the **kwargs dict
            srch_collcountry = form.cleaned_data.get('srch_collcountry', None)
            request.session['srch_collcountry'] = srch_collcountry  # Extra line to set session variable to memorize form selections
            if srch_collcountry:
                #Add the country to the **kwargs dict
                search_filter_kwargs['prof_user__college__college_country'] = srch_collcountry
            #Add the state to the kwargs dict
            srch_collstate = form.cleaned_data.get('srch_collstate', None)
            if srch_collstate: search_filter_kwargs['prof_user__college__college_state'] = srch_collstate
            #Add the college to the kwargs dict
            srch_collname = form.cleaned_data.get('srch_collname', None)
            if srch_collname: search_filter_kwargs['prof_user__college__college_name'] = srch_collname

            srch_major_raw = form.cleaned_data.get('srch_major', None) # raw Major needs to be converted to object as the field has a Foreign key relationship to the model Major
            if srch_major_raw:
                srch_major_raw = srch_major_raw.strip()
                try:
                    srch_major = Major.objects.get(major_name__iexact = srch_major_raw)
                except:
                    srch_major = None

                if srch_major: search_filter_kwargs['prof_major'] = srch_major

            # Show only valid users
            search_filter_kwargs['prof_user__is_active'] = True
            search_filter_kwargs['prof_user__is_verified'] = True

            # Show only published profiles
            search_filter_kwargs['prof_published'] = True
            search_filter_kwargs['prof_deactivated'] = False

            # get the UserProfile Queryset based on the above filter args and kwargs used in the search form. Reverse-order by profile created date
            # -------------------------------------------------------------------------------------------------------------------------------------
            search_filter_qs = UserProfile.objects.filter(*search_filter_args, **search_filter_kwargs).order_by('-prof_created')


            # Build the UserProfile Queryset based on the privacy filters of all users
            # ------------------------------------------------------------------------
            if not request.user.is_staff:  #Since privacy filter not applicable to Admin as user

                #Get the major and college information for the user who is searching
                request_user_profile_major = request.user.get_approved_profile().prof_major # returns the Major or None
                request_user_profile_college = request.user.college

                #Build the *args filter list using a Q objects for the privacy filter criterion

                # The logic:

                # Privacy filter for restricting view of those users who requested not be displayed to othes who are in the same college
                # Q( prof_user__college = request_user_profile_college, prof_user__preference__restrict_same_college = True )

                # Privacy filter for restricting view of those users who requested not be displayed to others having the same Major in the same college
                # Q( prof_user__college = request_user_profile_college, prof_major = request_user_profile_major, prof_user__preference__restrict_major = True  )

                # Privacy filter for restricting view of those users who do not want to be displayed to anyone outside their own college
                # Q( ~Q(prof_user__college = request_user_profile_college), prof_user__preference__restrict_other_colleges = True )

                privacy_filter_args = ( Q( prof_user__college = request_user_profile_college, prof_user__preference__restrict_same_college = True ) | Q( prof_user__college = request_user_profile_college, prof_major = request_user_profile_major, prof_user__preference__restrict_major = True  ) | Q( ~Q(prof_user__college = request_user_profile_college), prof_user__preference__restrict_other_colleges = True ), )

                # Additional criterion for only considering valid profiles using *kwargs list
                privacy_filter_kwargs = {}
                privacy_filter_kwargs['prof_user__is_active'] = True
                privacy_filter_kwargs['prof_user__is_verified'] = True
                privacy_filter_kwargs['prof_published'] = True
                privacy_filter_kwargs['prof_deactivated'] = False

                privacy_filter_qs = UserProfile.objects.filter(*privacy_filter_args, **privacy_filter_kwargs).order_by('-prof_created')
            else:
                privacy_filter_qs = None


            # Using the exclude set operation "A.exclude(pk__in = B)" method to subtract "privacy_filter_qs" FROM "search_filter_qs"

            if not request.user.is_staff: # For searching user as long as user is not Admin
                profile_results = search_filter_qs.exclude(pk__in = privacy_filter_qs)
            else: # For Admin user
                profile_results = search_filter_qs

            return render(request, 'searchprofiles/student_search_results.html', { 'profile_results': profile_results })

        # else form is not valid
        # return render(request, 'searchprofiles/search_student_profiles.html', {'form': form})


    else: # Present the Search Form if initial visit rather than form submission

        # Only present the form to users who can search if they are not in restricted status OR if user is Admin
        if not request.user.restricted() or request.user.is_staff:
            form = StudentSearchForm(request=request, userprofile=request.user.get_approved_profile()) #get_approved_profile() returns profile object or None
        else: # If user is restricted redirect to the restricted page
            return redirect('useracct:restricted')

    # Present the initial state of the form when visiting the page or the form with error / warnings from a form submit that failed validation
    return render(request, 'searchprofiles/search_student_profiles.html', {'form': form})
